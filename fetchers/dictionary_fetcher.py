"""
Dictionary fetcher for definitions, parts of speech, sentences, and phrases.

Primary source: Merriam-Webster's Learner's Dictionary API
Fallback source: Free Dictionary API (when rate limited)

Key features:
- Fetches definitions, POS, example sentences, and phrases/idioms from MW Learner's
- Falls back to Free Dictionary when MW is unavailable or rate limited
- Provides rate limit tracking and user feedback
- Supports save/resume functionality when rate limits are encountered
"""

import re
import time
import requests
from typing import Dict, List, Set, Optional, Tuple
from enum import Enum
from datetime import datetime, timedelta

from ..config import (
    URLS, API_DELAY, MERRIAM_WEBSTER_LEARNERS_KEY, 
    EXCLUDED_WORDS, RATE_LIMITS
)
from ..utils.cache import cache_get, cache_set


class DataSourceMode(Enum):
    """Mode for fetching data."""
    MW_PREFERRED = "mw_preferred"  # Try Merriam-Webster first, fall back to Free Dict
    FREE_DICTIONARY_ONLY = "free_dictionary_only"  # Only use Free Dictionary
    OVERNIGHT = "overnight"  # MW with long delays for rate limits


class RateLimitError(Exception):
    """Raised when API rate limit is exceeded."""
    def __init__(self, message: str, reset_time: Optional[datetime] = None, 
                 api_name: str = "unknown"):
        super().__init__(message)
        self.reset_time = reset_time
        self.api_name = api_name


class DictionaryFetcher:
    """
    Fetches word definitions from Merriam-Webster Learner's Dictionary.
    Falls back to Free Dictionary when rate limited.
    
    MW Learner's provides:
    - Definitions with usage labels
    - Part of speech
    - Example sentences (called "vis" in MW format)
    - Phrases/idioms (called "dros" - defined run-ons)
    """
    
    # Parts of speech we accept for wordbank
    VALID_POS = {'noun', 'verb', 'adjective', 'adverb'}
    
    # POS that should be filtered out
    EXCLUDED_POS = {'preposition', 'conjunction', 'pronoun', 'interjection', 
                    'determiner', 'article', 'particle', 'abbreviation',
                    'affix', 'prefix', 'suffix'}
    
    # MW POS abbreviations to full names
    MW_POS_MAP = {
        'noun': 'noun',
        'verb': 'verb',
        'adjective': 'adjective',
        'adverb': 'adverb',
        'adj': 'adjective',
        'adv': 'adverb',
        'n': 'noun',
        'v': 'verb',
        'vb': 'verb',
        'transitive verb': 'verb',
        'intransitive verb': 'verb',
    }
    
    # Definition labels that indicate uncommon/technical usage
    UNCOMMON_LABELS = {
        'archaic', 'obsolete', 'rare', 'dated', 'historical',
        'technical', 'computing', 'programming', 'mathematics',
        'logic', 'philosophy', 'law', 'legal', 'medicine', 'medical',
        'chemistry', 'physics', 'biology', 'botany', 'zoology',
        'anatomy', 'linguistics', 'grammar', 'rhetoric',
        'dialectal', 'regional', 'slang', 'vulgar', 'offensive',
        'british', 'scottish', 'irish', 'australian', 
        'nautical', 'military', 'heraldry',
    }
    
    # Note: All words are processed uniformly without special POS overrides.
    # The POS is determined from the API response or source data.
    # No hardcoded word->POS mappings to ensure consistent behavior.
    
    def __init__(self, mode: DataSourceMode = DataSourceMode.MW_PREFERRED):
        """
        Initialize dictionary fetcher.
        
        Args:
            mode: Data source mode
        """
        self.word_list: Set[str] = set()
        self._word_list_fetched = False
        self.definition_cache: Dict[str, Dict] = {}
        self.mode = mode
        
        # API status tracking
        self._mw_available = True
        self._mw_rate_limited = False
        self._mw_auth_error = False
        self._last_mw_error = ""
        self._requests_today = 0
        self._day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self._requests_this_minute = 0
        self._minute_start = time.time()
        
        # Rate limit settings
        self._rate_limit_per_day = RATE_LIMITS['merriam_webster']['requests_per_day']
        self._rate_limit_per_minute = RATE_LIMITS['merriam_webster']['requests_per_minute']
        
        # Overnight mode delay (seconds between requests)
        self._overnight_delay = 3  # ~20 requests/min, safe margin
    
    def fetch_word_list(self) -> bool:
        """Fetch the English word list for validation."""
        if self._word_list_fetched:
            return True
        
        # Check cache
        cached = cache_get("english_word_list_v3")
        if cached:
            self.word_list = set(cached)
            self._word_list_fetched = True
            return True
        
        print("📚 Fetching English word list...")
        
        try:
            resp = requests.get(URLS['english_words'], timeout=60)
            resp.raise_for_status()
            data = resp.json()
            
            # Filter to reasonable words
            self.word_list = {
                word.lower() for word in data.keys()
                if 3 <= len(word) <= 15 and word.isalpha()
            }
            
            # Cache
            cache_set("english_word_list_v3", list(self.word_list))
            
            print(f"   ✓ Loaded {len(self.word_list)} words")
            self._word_list_fetched = True
            return True
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch word list: {e}")
            return False
    
    def is_valid_word(self, word: str) -> bool:
        """Check if a word is in the dictionary."""
        if not self._word_list_fetched:
            self.fetch_word_list()
        return word.lower() in self.word_list
    
    def set_mode(self, mode: DataSourceMode):
        """Set the data source mode."""
        self.mode = mode
        print(f"📖 Dictionary mode set to: {mode.value}")
    
    def get_status(self) -> Dict:
        """Get current API status information."""
        return {
            'mode': self.mode.value,
            'mw_available': self._mw_available,
            'mw_rate_limited': self._mw_rate_limited,
            'mw_auth_error': self._mw_auth_error,
            'last_error': self._last_mw_error,
            'rate_limits': {
                'per_day': self._rate_limit_per_day,
                'per_minute': self._rate_limit_per_minute,
                'used_today': self._requests_today,
                'used_this_minute': self._requests_this_minute,
            },
            'recommendation': self._get_recommendation(),
            'reset_time': self._get_reset_time(),
        }
    
    def _get_recommendation(self) -> str:
        """Get a recommendation based on current status."""
        if self._mw_auth_error:
            return "Merriam-Webster API key invalid. Please check MW_LEARNERS_API_KEY or use Free Dictionary mode."
        elif self._mw_rate_limited:
            reset_time = self._get_reset_time()
            return f"Rate limited. Reset at {reset_time}. Options: wait, use overnight mode, or switch to Free Dictionary."
        elif not MERRIAM_WEBSTER_LEARNERS_KEY:
            return "No MW API key. Using Free Dictionary (standard quality)."
        elif self._mw_available:
            return "Merriam-Webster available. Using highest quality data source."
        else:
            return "Using Free Dictionary as fallback."
    
    def _get_reset_time(self) -> str:
        """Get when rate limits will reset."""
        if self._requests_this_minute >= self._rate_limit_per_minute:
            reset = datetime.now() + timedelta(seconds=60 - (time.time() - self._minute_start))
            return reset.strftime("%H:%M:%S")
        elif self._requests_today >= self._rate_limit_per_day:
            tomorrow = self._day_start + timedelta(days=1)
            return tomorrow.strftime("%Y-%m-%d 00:00:00")
        return "N/A"
    
    def _check_rate_limits(self) -> bool:
        """Check if we're within rate limits. Returns True if we can make a request."""
        now = time.time()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Reset daily counter
        if today > self._day_start:
            self._requests_today = 0
            self._day_start = today
            self._mw_rate_limited = False
        
        # Reset minute counter
        if now - self._minute_start > 60:
            self._requests_this_minute = 0
            self._minute_start = now
        
        # Check limits
        if self._requests_this_minute >= self._rate_limit_per_minute:
            return False
        if self._requests_today >= self._rate_limit_per_day:
            return False
        
        return True
    
    def _record_request(self):
        """Record an API request."""
        self._requests_this_minute += 1
        self._requests_today += 1
    
    def _handle_mw_error(self, status_code: int, response_text: str = ""):
        """Handle Merriam-Webster API errors."""
        if status_code == 401 or status_code == 403:
            self._mw_auth_error = True
            self._mw_available = False
            self._last_mw_error = f"{status_code} - Invalid API key"
            print(f"\n⚠️  MW AUTH ERROR: {status_code}")
            print("   Please check your MW_LEARNERS_API_KEY.")
            print("   Falling back to Free Dictionary.\n")
        
        elif status_code == 429:
            self._mw_rate_limited = True
            self._last_mw_error = "429 Too Many Requests - Rate limited"
            print("\n⚠️  MW RATE LIMIT EXCEEDED")
            print(f"   Used: {self._requests_today} requests today")
            print("   Options:")
            print("   1. Wait for rate limit to reset")
            print("   2. Switch to 'overnight' mode")
            print("   3. Switch to Free Dictionary mode\n")
        
        else:
            self._last_mw_error = f"HTTP {status_code}"
    
    def wait_for_rate_limit(self) -> int:
        """Wait for rate limit to reset. Returns seconds waited."""
        now = time.time()
        
        if self._requests_this_minute >= self._rate_limit_per_minute:
            wait_time = int(60 - (now - self._minute_start)) + 1
            print(f"⏳ Waiting {wait_time}s for minute rate limit to reset...")
            time.sleep(wait_time)
            self._requests_this_minute = 0
            self._minute_start = time.time()
            return wait_time
        
        if self._requests_today >= self._rate_limit_per_day:
            tomorrow = self._day_start + timedelta(days=1)
            wait_time = int((tomorrow - datetime.now()).total_seconds()) + 1
            print(f"⏳ Daily limit reached. Reset at midnight.")
            # Don't actually wait for daily reset - raise error instead
            raise RateLimitError(
                "Daily rate limit exceeded",
                reset_time=tomorrow,
                api_name="merriam_webster"
            )
        
        return 0
    
    def fetch_definition(self, word: str) -> Optional[Dict]:
        """
        Fetch definition data for a word.
        
        Returns dict with:
            - word: the word
            - definition: main definition
            - pos: part of speech
            - example: example sentence
            - examples: list of all examples
            - phrases: list of phrases/idioms
            - all_pos: list of all POS this word can be
            
        Returns None if word should be excluded.
        """
        word_lower = word.lower().strip()
        
        # Check if word is in EXCLUDED_WORDS
        if word_lower in EXCLUDED_WORDS:
            return None
        
        # Check cache
        cache_key = f"definition_mw_v1_{word_lower}"
        cached = cache_get(cache_key)
        if cached:
            if cached.get('excluded'):
                return None
            return cached if cached.get('definition') else None
        
        result = {
            'word': word,
            'definition': '',
            'pos': '',
            'example': '',
            'examples': [],
            'phrases': [],
            'all_pos': [],
        }
        
        # Try Merriam-Webster first (no POS preference - let API determine)
        if MERRIAM_WEBSTER_LEARNERS_KEY and self.mode != DataSourceMode.FREE_DICTIONARY_ONLY:
            mw_result = self._fetch_from_mw(word_lower, expected_pos=None)
            if mw_result and mw_result.get('definition'):
                result.update(mw_result)
        
        # Fall back to Free Dictionary if MW didn't work
        if not result['definition']:
            time.sleep(API_DELAY)
            free_dict_result = self._fetch_from_free_dictionary(word_lower, expected_pos=None)
            if free_dict_result:
                if not result['definition']:
                    result['definition'] = free_dict_result.get('definition', '')
                if not result['pos']:
                    result['pos'] = free_dict_result.get('pos', '')
                if not result['example']:
                    result['example'] = free_dict_result.get('example', '')
                
                result['all_pos'] = list(set(
                    result['all_pos'] + free_dict_result.get('all_pos', [])
                ))
                result['examples'] = list(set(
                    result.get('examples', []) + free_dict_result.get('examples', [])
                ))
        
        # Check if POS is excluded
        if result['pos'] in self.EXCLUDED_POS:
            cache_set(cache_key, {'excluded': True, 'pos': result['pos']})
            return None
        
        # Cache the result
        cache_set(cache_key, result)
        
        return result if result['definition'] else None
    
    def _fetch_from_mw(self, word: str, expected_pos: str = None) -> Optional[Dict]:
        """
        Fetch from Merriam-Webster Learner's Dictionary API.
        
        MW Learner's Dictionary provides:
        - Definitions with labels
        - Part of speech (fl field)
        - Example sentences (vis field)
        - Phrases/idioms (dros - defined run-ons)
        """
        if not MERRIAM_WEBSTER_LEARNERS_KEY:
            return None
        
        if self._mw_auth_error:
            return None
        
        if self.mode == DataSourceMode.FREE_DICTIONARY_ONLY:
            return None
        
        # Check rate limits
        if not self._check_rate_limits():
            if self.mode == DataSourceMode.OVERNIGHT:
                self.wait_for_rate_limit()
            else:
                self._mw_rate_limited = True
                return None
        
        result = {
            'definition': '',
            'pos': '',
            'example': '',
            'examples': [],
            'phrases': [],
            'all_pos': [],
        }
        
        try:
            url = f"{URLS['mw_learners']}/{word}"
            params = {'key': MERRIAM_WEBSTER_LEARNERS_KEY}
            
            resp = requests.get(url, params=params, timeout=10)
            self._record_request()
            
            if resp.status_code in [401, 403, 429]:
                self._handle_mw_error(resp.status_code, resp.text)
                return None
            
            if resp.status_code != 200:
                self._handle_mw_error(resp.status_code)
                return None
            
            self._mw_available = True
            data = resp.json()
            
            if not data:
                return None
            
            # MW returns list of strings if word not found (suggestions)
            if isinstance(data[0], str):
                return None
            
            # Collect all POS
            for entry in data:
                if isinstance(entry, dict):
                    pos = entry.get('fl', '').lower()
                    pos = self.MW_POS_MAP.get(pos, pos)
                    if pos and pos not in result['all_pos']:
                        result['all_pos'].append(pos)
            
            # Find the best entry
            best_entry = None
            best_score = -1
            
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                
                pos = entry.get('fl', '').lower()
                pos = self.MW_POS_MAP.get(pos, pos)
                
                # Skip excluded POS
                if pos in self.EXCLUDED_POS:
                    continue
                
                # Calculate score
                score = 0
                
                if expected_pos and pos == expected_pos:
                    score += 100
                
                if pos in ['noun', 'verb', 'adjective']:
                    score += 10
                
                # Check for examples
                if entry.get('def'):
                    for sense in entry['def']:
                        if sense.get('sseq'):
                            for sseq in sense['sseq']:
                                for item in sseq:
                                    if isinstance(item, list) and len(item) > 1:
                                        if isinstance(item[1], dict) and item[1].get('dt'):
                                            score += 5
                
                if score > best_score:
                    best_score = score
                    best_entry = entry
            
            if best_entry:
                result['pos'] = self.MW_POS_MAP.get(
                    best_entry.get('fl', '').lower(), 
                    best_entry.get('fl', '').lower()
                )
                
                # Extract definition and examples from MW format
                definition, examples = self._parse_mw_definition(best_entry)
                result['definition'] = definition
                result['examples'] = examples
                if examples:
                    result['example'] = examples[0]
                
                # Extract phrases (dros - defined run-ons)
                phrases = self._parse_mw_phrases(best_entry)
                result['phrases'] = phrases
            
            # Apply overnight mode delay
            if self.mode == DataSourceMode.OVERNIGHT:
                time.sleep(self._overnight_delay)
            
            return result
            
        except requests.exceptions.Timeout:
            self._last_mw_error = "Request timeout"
            return None
        except requests.exceptions.ConnectionError:
            self._last_mw_error = "Connection error"
            self._mw_available = False
            return None
        except Exception as e:
            self._last_mw_error = str(e)
            return None
    
    def _parse_mw_definition(self, entry: Dict) -> Tuple[str, List[str]]:
        """
        Parse definition and examples from MW Learner's entry.
        
        MW format:
        - def: list of definition groups
        - sseq: sense sequences
        - dt: definition text (list of items)
        - vis: verbal illustrations (examples)
        """
        definition = ""
        examples = []
        
        def_list = entry.get('def', [])
        
        for def_group in def_list:
            sseq = def_group.get('sseq', [])
            
            for sense_seq in sseq:
                for item in sense_seq:
                    if not isinstance(item, list) or len(item) < 2:
                        continue
                    
                    item_type = item[0]
                    item_data = item[1]
                    
                    if item_type == 'sense' and isinstance(item_data, dict):
                        dt = item_data.get('dt', [])
                        
                        for dt_item in dt:
                            if isinstance(dt_item, list) and len(dt_item) >= 2:
                                dt_type = dt_item[0]
                                dt_content = dt_item[1]
                                
                                if dt_type == 'text' and not definition:
                                    # Clean up definition text
                                    definition = self._clean_mw_text(dt_content)
                                
                                elif dt_type == 'vis':
                                    # Extract examples
                                    for vis in dt_content:
                                        if isinstance(vis, dict) and vis.get('t'):
                                            example = self._clean_mw_text(vis['t'])
                                            if example and example not in examples:
                                                examples.append(example)
        
        return definition, examples
    
    def _parse_mw_phrases(self, entry: Dict) -> List[str]:
        """
        Parse phrases/idioms from MW Learner's entry.
        
        MW format:
        - dros: defined run-ons (phrases)
        - drp: phrase text
        """
        phrases = []
        
        dros = entry.get('dros', [])
        
        for dro in dros:
            if isinstance(dro, dict) and dro.get('drp'):
                phrase = self._clean_mw_text(dro['drp'])
                if phrase and phrase not in phrases:
                    phrases.append(phrase)
        
        # Also check for "uro" (undefined run-ons) which may contain forms
        uros = entry.get('uros', [])
        for uro in uros:
            if isinstance(uro, dict) and uro.get('ure'):
                # Skip simple word forms, only get phrases
                ure = uro['ure']
                if ' ' in ure:  # Only if it's a phrase
                    phrase = self._clean_mw_text(ure)
                    if phrase and phrase not in phrases:
                        phrases.append(phrase)
        
        return phrases
    
    def _clean_mw_text(self, text: str) -> str:
        """
        Clean MW text by removing markup.
        
        MW uses various tags like {bc}, {it}, {ldquo}, etc.
        """
        if not text:
            return ""
        
        # Remove MW-specific markup
        text = re.sub(r'\{bc\}', '', text)  # Beginning colon
        text = re.sub(r'\{it\}([^{]*)\{/it\}', r'\1', text)  # Italic
        text = re.sub(r'\{b\}([^{]*)\{/b\}', r'\1', text)  # Bold
        text = re.sub(r'\{inf\}([^{]*)\{/inf\}', r'\1', text)  # Inferior
        text = re.sub(r'\{sup\}([^{]*)\{/sup\}', r'\1', text)  # Superior
        text = re.sub(r'\{ldquo\}', '"', text)  # Left quote
        text = re.sub(r'\{rdquo\}', '"', text)  # Right quote
        text = re.sub(r'\{phrase\}([^{]*)\{/phrase\}', r'\1', text)
        text = re.sub(r'\{wi\}([^{]*)\{/wi\}', r'\1', text)  # Word illustration
        text = re.sub(r'\{gloss\}([^{]*)\{/gloss\}', r'\1', text)
        text = re.sub(r'\{dx\}.*?\{/dx\}', '', text)  # Cross-reference
        text = re.sub(r'\{dx_def\}.*?\{/dx_def\}', '', text)
        text = re.sub(r'\{dx_ety\}.*?\{/dx_ety\}', '', text)
        text = re.sub(r'\{a_link\|([^}]*)\}', r'\1', text)  # Links
        text = re.sub(r'\{d_link\|([^|]*)\|[^}]*\}', r'\1', text)
        text = re.sub(r'\{sx\|([^|]*)\|[^}]*\}', r'\1', text)
        text = re.sub(r'\{[^}]+\}', '', text)  # Any remaining tags
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _fetch_from_free_dictionary(self, word: str, expected_pos: str = None) -> Optional[Dict]:
        """Fetch from Free Dictionary API (fallback)."""
        try:
            url = f"{URLS['free_dictionary']}/{word}"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            if not data or not isinstance(data, list):
                return None
            
            entry = data[0]
            result = {
                'definition': '',
                'pos': '',
                'example': '',
                'examples': [],
                'phrases': [],
                'all_pos': [],
            }
            
            # Collect all POS first
            for meaning in entry.get('meanings', []):
                pos = meaning.get('partOfSpeech', '').lower()
                if pos and pos not in result['all_pos']:
                    result['all_pos'].append(pos)
            
            # Find the best definition
            best_def = None
            best_pos = None
            best_score = -1
            
            for meaning in entry.get('meanings', []):
                pos = meaning.get('partOfSpeech', '').lower()
                
                if pos in self.EXCLUDED_POS:
                    continue
                
                for defn in meaning.get('definitions', []):
                    text = defn.get('definition', '')
                    
                    score = 0
                    
                    if expected_pos and pos == expected_pos:
                        score += 100
                    
                    if pos in ['noun', 'verb', 'adjective']:
                        score += 10
                    
                    if defn.get('example'):
                        score += 5
                    
                    if 20 <= len(text) <= 150:
                        score += 3
                    
                    if score > best_score:
                        best_score = score
                        best_def = defn
                        best_pos = pos
            
            if best_def:
                result['definition'] = best_def.get('definition', '')
                result['pos'] = best_pos
                result['example'] = best_def.get('example', '')
                if result['example']:
                    result['examples'] = [result['example']]
            
            # Collect all examples
            for meaning in entry.get('meanings', []):
                for defn in meaning.get('definitions', []):
                    example = defn.get('example', '')
                    if example and example not in result['examples']:
                        result['examples'].append(example)
            
            return result
            
        except Exception as e:
            return None
    
    def get_pos(self, word: str) -> str:
        """Get the primary part of speech for a word from API."""
        result = self.fetch_definition(word)
        return result.get('pos', '') if result else ''
    
    def validate_pos(self, word: str, expected_pos: str) -> bool:
        """Check if a word can be used as a specific POS."""
        result = self.fetch_definition(word)
        if not result:
            return False
        
        all_pos = result.get('all_pos', [])
        return expected_pos in all_pos or result.get('pos') == expected_pos

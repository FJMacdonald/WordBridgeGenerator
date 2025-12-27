"""
Oxford 3000-based wordbank generator.

This module generates a wordbank using the Oxford 3000 word list as the source,
extracting nouns, verbs, and adjectives.

Key features:
- Uses Oxford 3000 CSV as source (nouns, verbs, adjectives only)
- First POS used when multiple are listed (e.g., "verb, noun" -> "verb")
- Synonyms/Antonyms: Uses Oxford CSV values (converting "none" to []) + MW Thesaurus
- Categories: Array with BehrouzSohrabi, Datamuse, and WordNet sources
- Emoji fallback: BehrouzSohrabi -> OpenMoji -> Noun Project
- Associated words: From Free Association CSV files
- Test mode: Saves all API returns for verification
- Generates issues report
"""

import csv
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field

from ..config import (
    DATA_DIR, API_DELAY, EXCLUDED_WORDS, URLS,
    MERRIAM_WEBSTER_LEARNERS_KEY, MERRIAM_WEBSTER_THESAURUS_KEY,
    FREE_ASSOCIATION_DIR, USF_FILE_MAPPING
)
from ..utils.cache import cache_get, cache_set
from .wordbank_manager import WordEntry, WordbankManager
from .sound_detector import SoundGroupDetector
from .distractor_generator import DistractorGenerator


# Try to import WordNet, but handle gracefully if unavailable
try:
    from nltk.corpus import wordnet as wn
    WORDNET_AVAILABLE = True
except (ImportError, LookupError):
    WORDNET_AVAILABLE = False
    wn = None


@dataclass
class IssueReport:
    """Tracks issues encountered during wordbank generation."""
    api_errors: List[Dict] = field(default_factory=list)
    words_without_emoji: List[str] = field(default_factory=list)
    words_without_definition: List[str] = field(default_factory=list)
    words_without_associated: List[str] = field(default_factory=list)
    words_without_categories: List[str] = field(default_factory=list)
    words_without_synonyms: List[str] = field(default_factory=list)
    words_without_antonyms: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "api_errors": self.api_errors,
            "words_without_emoji": self.words_without_emoji,
            "words_without_definition": self.words_without_definition,
            "words_without_associated": self.words_without_associated,
            "words_without_categories": self.words_without_categories,
            "words_without_synonyms": self.words_without_synonyms,
            "words_without_antonyms": self.words_without_antonyms,
            "summary": {
                "total_api_errors": len(self.api_errors),
                "total_without_emoji": len(self.words_without_emoji),
                "total_without_definition": len(self.words_without_definition),
                "total_without_associated": len(self.words_without_associated),
                "total_without_categories": len(self.words_without_categories),
                "total_without_synonyms": len(self.words_without_synonyms),
                "total_without_antonyms": len(self.words_without_antonyms),
            }
        }


class OxfordWordbankGenerator:
    """
    Generates wordbank entries from Oxford 3000 word list.
    
    Features:
    - Extracts nouns, verbs, adjectives from Oxford 3000
    - Uses first POS when multiple listed
    - Uniform rules for all words (no special cases)
    - Test mode saves all API responses
    """
    
    # Valid parts of speech to extract
    VALID_POS = {'noun', 'verb', 'adjective'}
    
    def __init__(self, test_mode: bool = False, test_word_count: int = 10):
        """
        Initialize the generator.
        
        Args:
            test_mode: If True, save all API responses and limit to test_word_count words
            test_word_count: Number of words to process in test mode
        """
        self.test_mode = test_mode
        self.test_word_count = test_word_count
        self.issues = IssueReport()
        
        # API response storage for test mode
        self.api_responses: Dict[str, Dict] = {}
        
        # Initialize components
        self.sound_detector = SoundGroupDetector()
        
        # Emoji data caches
        self._behrouzsohrabi_data: Dict[str, Dict] = {}
        self._openmoji_data: Dict[str, Dict] = {}
        self._emoji_keyword_index: Dict[str, List[Tuple[str, Dict, str]]] = {}  # keyword -> [(emoji, meta, source)]
        
        # Free association data
        self._usf_data: Dict[str, List[Tuple[str, int]]] = {}
        self._usf_loaded: Set[str] = set()
        
        print(f"\n🚀 Oxford Wordbank Generator initialized")
        print(f"   Test mode: {test_mode}")
        if test_mode:
            print(f"   Test word count: {test_word_count}")
        print(f"   WordNet available: {WORDNET_AVAILABLE}")
        print()
    
    def load_oxford_3000(self) -> List[Dict]:
        """
        Load and parse Oxford 3000 CSV file.
        
        Returns list of dicts with:
        - word: the word
        - pos: first part of speech (noun, verb, or adjective)
        - definition: Oxford definition
        - synonyms: list (empty if "none")
        - antonyms: list (empty if "none")
        """
        oxford_path = DATA_DIR / "Oxford3000.csv"
        
        if not oxford_path.exists():
            raise FileNotFoundError(f"Oxford 3000 CSV not found at {oxford_path}")
        
        words = []
        
        with open(oxford_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                word = row.get('Word', '').strip().lower()
                pos_raw = row.get('Part of Speech', '').strip().lower()
                definition = row.get('Definition', '').strip()
                synonyms_raw = row.get('Synonyms', '').strip()
                antonyms_raw = row.get('Antonyms', '').strip()
                
                if not word:
                    continue
                
                # Skip excluded words
                if word in EXCLUDED_WORDS:
                    continue
                
                # Parse POS - use first one if multiple
                pos_parts = [p.strip() for p in pos_raw.split(',')]
                pos = None
                for p in pos_parts:
                    if p in self.VALID_POS:
                        pos = p
                        break
                
                # Skip if no valid POS
                if not pos:
                    continue
                
                # Parse synonyms - convert "none" to empty list
                if synonyms_raw.lower() == 'none' or not synonyms_raw:
                    synonyms = []
                else:
                    synonyms = [s.strip() for s in synonyms_raw.split(',') if s.strip()]
                
                # Parse antonyms - convert "none" to empty list
                if antonyms_raw.lower() == 'none' or not antonyms_raw:
                    antonyms = []
                else:
                    antonyms = [a.strip() for a in antonyms_raw.split(',') if a.strip()]
                
                words.append({
                    'word': word,
                    'pos': pos,
                    'definition': definition,
                    'synonyms': synonyms,
                    'antonyms': antonyms,
                })
        
        print(f"📚 Loaded {len(words)} words from Oxford 3000 (nouns, verbs, adjectives)")
        return words
    
    def _fetch_emoji_data(self):
        """Fetch emoji data from BehrouzSohrabi and OpenMoji sources.
        
        Note: These are not logged in api_responses per user request.
        """
        
        # 1. Fetch BehrouzSohrabi/Emoji
        print("😀 Fetching emoji data from BehrouzSohrabi/Emoji...")
        try:
            resp = requests.get(URLS['emoji_categories'], timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            # Not logging to api_responses per user request
            
            for category, emoji_list in data.items():
                if not isinstance(emoji_list, list):
                    continue
                for item in emoji_list:
                    if not isinstance(item, dict):
                        continue
                    emoji_char = item.get('emoji', '')
                    if not emoji_char:
                        continue
                    
                    text = item.get('text', '').lower() if item.get('text') else ''
                    keywords_raw = item.get('keywords', [])
                    if isinstance(keywords_raw, str):
                        keywords = [k.strip().lower() for k in keywords_raw.split(',') if k.strip()]
                    elif isinstance(keywords_raw, list):
                        keywords = [k.lower() if isinstance(k, str) else str(k).lower() for k in keywords_raw]
                    else:
                        keywords = []
                    
                    meta = {
                        'text': text,
                        'keywords': keywords,
                        'category': category,
                    }
                    self._behrouzsohrabi_data[emoji_char] = meta
                    
                    # Index by keywords
                    for kw in keywords:
                        if kw not in self._emoji_keyword_index:
                            self._emoji_keyword_index[kw] = []
                        self._emoji_keyword_index[kw].append((emoji_char, meta, 'BehrouzSohrabi'))
            
            print(f"   ✓ Loaded {len(self._behrouzsohrabi_data)} emojis from BehrouzSohrabi")
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch BehrouzSohrabi emoji data: {e}")
            self.issues.api_errors.append({
                'source': 'BehrouzSohrabi',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        
        time.sleep(API_DELAY)
        
        # 2. Fetch OpenMoji
        print("😀 Fetching emoji data from OpenMoji...")
        openmoji_url = "https://raw.githubusercontent.com/hfg-gmuend/openmoji/master/data/openmoji.json"
        try:
            resp = requests.get(openmoji_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            # Not logging to api_responses per user request
            
            for item in data:
                if not isinstance(item, dict):
                    continue
                
                hexcode = item.get('hexcode', '')
                if not hexcode:
                    continue
                
                try:
                    emoji_char = ''.join(chr(int(code, 16)) for code in hexcode.split('-'))
                except (ValueError, OverflowError):
                    continue
                
                annotation = item.get('annotation', '').lower()
                tags = item.get('tags', '').lower().split(',') if item.get('tags') else []
                tags = [t.strip() for t in tags if t.strip()]
                group = item.get('group', '')
                subgroups = item.get('subgroups', '')
                
                meta = {
                    'text': annotation,
                    'keywords': tags + [annotation] if annotation else tags,
                    'category': group,
                    'subgroup': subgroups,
                }
                self._openmoji_data[emoji_char] = meta
                
                # Index by keywords (only if not already in BehrouzSohrabi)
                for kw in meta['keywords']:
                    if kw not in self._emoji_keyword_index:
                        self._emoji_keyword_index[kw] = []
                    # Add OpenMoji entries
                    self._emoji_keyword_index[kw].append((emoji_char, meta, 'OpenMoji'))
            
            print(f"   ✓ Loaded {len(self._openmoji_data)} emojis from OpenMoji")
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch OpenMoji data: {e}")
            self.issues.api_errors.append({
                'source': 'OpenMoji',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
    
    def _find_emoji(self, word: str, synonyms: List[str] = None) -> Tuple[str, str, str]:
        """
        Find emoji using fallback strategy:
        1. BehrouzSohrabi/Emoji
        2. OpenMoji
        3. Noun Project (leave blank if this also fails)
        
        Returns:
            Tuple of (emoji_char, category, source)
            If not found, returns ('', '', '')
        """
        synonyms = synonyms or []
        word_lower = word.lower()
        
        # Try word and synonyms
        search_terms = [word_lower] + [s.lower() for s in synonyms[:3]]
        
        for term in search_terms:
            if term in self._emoji_keyword_index:
                candidates = self._emoji_keyword_index[term]
                
                # Prefer BehrouzSohrabi, then OpenMoji
                for preferred_source in ['BehrouzSohrabi', 'OpenMoji']:
                    for emoji_char, meta, source in candidates:
                        if source == preferred_source:
                            # Skip flags unless searching for flag/country
                            if meta.get('category', '').lower() == 'flags' and 'flag' not in term:
                                continue
                            return (emoji_char, meta.get('category', ''), source)
        
        # Try word variations
        variations = self._get_word_variations(word_lower)
        for var in variations:
            if var in self._emoji_keyword_index:
                candidates = self._emoji_keyword_index[var]
                for preferred_source in ['BehrouzSohrabi', 'OpenMoji']:
                    for emoji_char, meta, source in candidates:
                        if source == preferred_source:
                            if meta.get('category', '').lower() == 'flags':
                                continue
                            return (emoji_char, meta.get('category', ''), source)
        
        # Try Noun Project as last resort
        noun_project_result = self._fetch_noun_project(word)
        if noun_project_result:
            return ('', noun_project_result.get('term', ''), 'NounProject')
        
        # No emoji found
        return ('', '', '')
    
    def _fetch_noun_project(self, word: str) -> Optional[Dict]:
        """Fetch icon from Noun Project API."""
        from ..config import NOUN_PROJECT_KEY, NOUN_PROJECT_SECRET
        
        if not NOUN_PROJECT_KEY or not NOUN_PROJECT_SECRET:
            if self.test_mode:
                self.api_responses[f'noun_project_{word}'] = {
                    'url': f"{URLS['noun_project']}?query={word}",
                    'error': 'No API credentials configured (NOUN_PROJECT_KEY/SECRET)',
                    'skipped': True
                }
                self.issues.api_errors.append({
                    'source': 'NounProject',
                    'word': word,
                    'error': 'No API credentials configured',
                    'timestamp': datetime.now().isoformat()
                })
            return None
        
        try:
            import base64
            import hashlib
            import hmac
            from urllib.parse import quote
            
            url = f"{URLS['noun_project']}?query={quote(word)}&limit=1"
            
            # OAuth 1.0 authentication
            timestamp = str(int(time.time()))
            nonce = hashlib.md5(f"{timestamp}{word}".encode()).hexdigest()
            
            oauth_params = {
                'oauth_consumer_key': NOUN_PROJECT_KEY,
                'oauth_nonce': nonce,
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': timestamp,
                'oauth_version': '1.0',
            }
            
            base_params = '&'.join(f'{k}={quote(str(v), safe="")}' 
                                   for k, v in sorted(oauth_params.items()))
            base_string = f"GET&{quote(URLS['noun_project'], safe='')}&{quote(base_params, safe='')}"
            
            signing_key = f"{NOUN_PROJECT_SECRET}&"
            signature = base64.b64encode(
                hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
            ).decode()
            
            oauth_params['oauth_signature'] = signature
            
            auth_header = 'OAuth ' + ', '.join(
                f'{k}="{quote(str(v), safe="")}"' 
                for k, v in sorted(oauth_params.items())
            )
            
            headers = {'Authorization': auth_header}
            
            resp = requests.get(url, headers=headers, timeout=10)
            
            # Always log API response in test mode
            if self.test_mode:
                try:
                    response_data = resp.json() if resp.status_code == 200 else resp.text[:500]
                except:
                    response_data = resp.text[:500]
                    
                self.api_responses[f'noun_project_{word}'] = {
                    'url': url,
                    'status': resp.status_code,
                    'response': response_data
                }
            
            if resp.status_code != 200:
                self.issues.api_errors.append({
                    'source': 'NounProject',
                    'word': word,
                    'status': resp.status_code,
                    'timestamp': datetime.now().isoformat()
                })
                return None
            
            data = resp.json()
            icons = data.get('icons', [])
            
            if not icons:
                return None
            
            icon = icons[0]
            return {
                'icon_url': icon.get('icon_url') or icon.get('preview_url'),
                'attribution': icon.get('attribution', 'Icon from The Noun Project'),
                'term': icon.get('term', word),
                'id': icon.get('id'),
            }
            
        except Exception as e:
            if self.test_mode:
                self.api_responses[f'noun_project_{word}'] = {
                    'url': f"{URLS['noun_project']}?query={word}",
                    'error': str(e)
                }
            self.issues.api_errors.append({
                'source': 'NounProject',
                'word': word,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            return None
    
    def _get_word_variations(self, word: str) -> List[str]:
        """Generate word variations (plural, verb forms, etc.)."""
        variations = []
        
        if word.endswith('s'):
            variations.append(word[:-1])
            if word.endswith('es'):
                variations.append(word[:-2])
            if word.endswith('ies'):
                variations.append(word[:-3] + 'y')
        else:
            variations.append(word + 's')
        
        if word.endswith('ing'):
            variations.append(word[:-3])
            variations.append(word[:-3] + 'e')
        elif word.endswith('ed'):
            variations.append(word[:-2])
            variations.append(word[:-2] + 'e')
        
        if word.endswith('ly'):
            variations.append(word[:-2])
        if word.endswith('er'):
            variations.append(word[:-2])
        if word.endswith('est'):
            variations.append(word[:-3])
        
        return [v for v in variations if len(v) >= 2]
    
    def _load_usf_file(self, first_letter: str) -> None:
        """Load USF Free Association Norms file for a letter."""
        first_letter = first_letter.upper()

        if first_letter in self._usf_loaded:
            if self.test_mode:
                print(f"      [DEBUG USF] Letter '{first_letter}' already loaded, {len([k for k in self._usf_data.keys() if k.startswith(first_letter)])} cues cached")
            return
        
        if first_letter not in USF_FILE_MAPPING:
            if self.test_mode:
                print(f"      [DEBUG USF] No file mapping for letter '{first_letter}'")
            self._usf_loaded.add(first_letter)
            return
        
        filename = USF_FILE_MAPPING[first_letter]
        filepath = FREE_ASSOCIATION_DIR / filename
        
        if self.test_mode:
            print(f"      [DEBUG USF] Looking for file: {filepath}")
            print(f"      [DEBUG USF] File exists: {filepath.exists()}")
        
        if not filepath.exists():
            if self.test_mode:
                print(f"      [DEBUG USF] File not found: {filepath}")
            self._usf_loaded.add(first_letter)
            return
        
        try:
            cues_loaded = 0
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                
                # Debug: print first row's keys
                if self.test_mode:
                    # Peek at headers
                    f.seek(0)
                    first_line = f.readline()
                    print(f"      [DEBUG USF] CSV headers: {first_line.strip()[:100]}...")
                    f.seek(0)
                    reader = csv.DictReader(f)
                
                for row in reader:
                    cue = row.get('CUE', '').strip().upper()
                    target = row.get('TARGET', '').strip()
                    
                    try:
                        # FSG is Forward Strength - probability of cue->target
                        fsg_str = row.get('FSG', '0').strip()
                        fsg = float(fsg_str) if fsg_str else 0
                    except (ValueError, TypeError):
                        fsg = 0
                    
                    if not cue or not target or fsg == 0:
                        continue
                    
                    # Skip multi-word targets
                    if ' ' in target:
                        continue
                    
                    if cue not in self._usf_data:
                        self._usf_data[cue] = []
                        cues_loaded += 1
                    
                    # Store with FSG for ranking
                    self._usf_data[cue].append((target.lower(), fsg))
            
            if self.test_mode:
                print(f"      [DEBUG USF] Loaded {cues_loaded} new cues from {filename}")
            
            self._usf_loaded.add(first_letter)
            
        except Exception as e:
            print(f"   ⚠ Error loading USF file {filepath}: {e}")
            import traceback
            if self.test_mode:
                traceback.print_exc()
            self._usf_loaded.add(first_letter)
    
    def _fetch_associated_words(self, word: str) -> List[str]:
        """Fetch associated words from USF Free Association Norms."""
        word_upper = word.upper()
        first_letter = word_upper[0] if word_upper else ''
        
        if self.test_mode:
            print(f"      [DEBUG ASSOC] Looking up word: '{word_upper}'")
        
        self._load_usf_file(first_letter)
        
        if self.test_mode:
            print(f"      [DEBUG ASSOC] Total cues loaded: {len(self._usf_data)}")
            # Check if word exists in data
            if word_upper in self._usf_data:
                print(f"      [DEBUG ASSOC] Found '{word_upper}' with {len(self._usf_data[word_upper])} associations")
            else:
                # Show some available cues starting with same letter
                sample_cues = [k for k in self._usf_data.keys() if k.startswith(first_letter)][:5]
                print(f"      [DEBUG ASSOC] '{word_upper}' NOT found. Sample cues with '{first_letter}': {sample_cues}")
        
        associations = self._usf_data.get(word_upper, [])
        
        if not associations:
            if self.test_mode:
                print(f"      [DEBUG ASSOC] No associations found for '{word_upper}'")
            return []
        
        # Sort by FSG (descending) and take top 5
        sorted_assoc = sorted(associations, key=lambda x: x[1], reverse=True)
        
        if self.test_mode:
            print(f"      [DEBUG ASSOC] Top associations for '{word_upper}': {sorted_assoc[:5]}")
        
        result = []
        for target, fsg in sorted_assoc:
            if target.lower() != word.lower() and len(target) >= 3:
                if target not in result:
                    result.append(target)
                if len(result) >= 5:
                    break
        
        if self.test_mode:
            print(f"      [DEBUG ASSOC] Final result: {result}")
        
        return result
    
    def _fetch_mw_thesaurus(self, word: str) -> Dict[str, List[str]]:
        """
        Fetch synonyms and antonyms from MW Intermediate Thesaurus.
        
        Returns dict with 'synonyms' and 'antonyms' lists.
        """
        result = {'synonyms': [], 'antonyms': []}
        
        if not MERRIAM_WEBSTER_THESAURUS_KEY:
            if self.test_mode:
                self.api_responses[f'mw_thesaurus_{word}'] = {
                    'url': f"{URLS['mw_thesaurus']}/{word}",
                    'error': 'No API key configured (MERRIAM_WEBSTER_THESAURUS_KEY)',
                    'skipped': True
                }
                self.issues.api_errors.append({
                    'source': 'MW_Thesaurus',
                    'word': word,
                    'error': 'No API key configured',
                    'timestamp': datetime.now().isoformat()
                })
            return result
        
        try:
            url = f"{URLS['mw_thesaurus']}/{word}"
            params = {'key': MERRIAM_WEBSTER_THESAURUS_KEY}
            
            resp = requests.get(url, params=params, timeout=10)
            
            # Always log API response in test mode
            if self.test_mode:
                try:
                    response_data = resp.json() if resp.status_code == 200 else resp.text[:500]
                except:
                    response_data = resp.text[:500]
                    
                self.api_responses[f'mw_thesaurus_{word}'] = {
                    'url': url,
                    'status': resp.status_code,
                    'response': response_data
                }
            
            if resp.status_code != 200:
                self.issues.api_errors.append({
                    'source': 'MW_Thesaurus',
                    'word': word,
                    'status': resp.status_code,
                    'timestamp': datetime.now().isoformat()
                })
                return result
            
            data = resp.json()
            
            if not data:
                return result
            
            # MW returns list of strings if word not found
            if isinstance(data[0], str):
                if self.test_mode:
                    self.api_responses[f'mw_thesaurus_{word}']['note'] = 'Word not found - suggestions returned'
                return result
            
            entry = data[0]
            if isinstance(entry, dict):
                meta = entry.get('meta', {})
                
                # Synonyms in meta.syns (list of lists)
                for syn_group in meta.get('syns', []):
                    for syn in syn_group:
                        if isinstance(syn, str) and ' ' not in syn and len(syn) >= 3:
                            if syn.lower() not in [s.lower() for s in result['synonyms']]:
                                result['synonyms'].append(syn)
                
                # Antonyms in meta.ants (list of lists)
                for ant_group in meta.get('ants', []):
                    for ant in ant_group:
                        if isinstance(ant, str) and ' ' not in ant and len(ant) >= 3:
                            if ant.lower() not in [a.lower() for a in result['antonyms']]:
                                result['antonyms'].append(ant)
            
            return result
            
        except Exception as e:
            if self.test_mode:
                self.api_responses[f'mw_thesaurus_{word}'] = {
                    'url': f"{URLS['mw_thesaurus']}/{word}",
                    'error': str(e)
                }
            self.issues.api_errors.append({
                'source': 'MW_Thesaurus',
                'word': word,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            return result
    
    def _fetch_mw_learners(self, word: str) -> Optional[Dict]:
        """
        Fetch definition, sentences, and idioms from MW Learner's Dictionary.
        
        Returns dict with:
        - definition: str
        - sentences: List[str]
        - idioms: List[str]
        """
        if not MERRIAM_WEBSTER_LEARNERS_KEY:
            if self.test_mode:
                self.api_responses[f'mw_learners_{word}'] = {
                    'url': f"{URLS['mw_learners']}/{word}",
                    'error': 'No API key configured (MERRIAM_WEBSTER_LEARNERS_KEY)',
                    'skipped': True
                }
                self.issues.api_errors.append({
                    'source': 'MW_Learners',
                    'word': word,
                    'error': 'No API key configured',
                    'timestamp': datetime.now().isoformat()
                })
            return None
        
        try:
            url = f"{URLS['mw_learners']}/{word}"
            params = {'key': MERRIAM_WEBSTER_LEARNERS_KEY}
            
            resp = requests.get(url, params=params, timeout=10)
            
            # Always log API response in test mode
            if self.test_mode:
                try:
                    response_data = resp.json() if resp.status_code == 200 else resp.text[:500]
                except:
                    response_data = resp.text[:500]
                    
                self.api_responses[f'mw_learners_{word}'] = {
                    'url': url,
                    'status': resp.status_code,
                    'response': response_data
                }
            
            if resp.status_code != 200:
                self.issues.api_errors.append({
                    'source': 'MW_Learners',
                    'word': word,
                    'status': resp.status_code,
                    'timestamp': datetime.now().isoformat()
                })
                return None
            
            data = resp.json()
            
            if not data:
                return None
            
            if isinstance(data[0], str):
                if self.test_mode:
                    self.api_responses[f'mw_learners_{word}']['note'] = 'Word not found - suggestions returned'
                return None
            
            result = {
                'definition': '',
                'sentences': [],
                'idioms': [],
            }
            
            entry = data[0]
            if not isinstance(entry, dict):
                return None
            
            # Parse definition and examples
            def_list = entry.get('def', [])
            for def_group in def_list:
                sseq = def_group.get('sseq', [])
                for sense_seq in sseq:
                    for item in sense_seq:
                        if not isinstance(item, list) or len(item) < 2:
                            continue
                        
                        if item[0] == 'sense' and isinstance(item[1], dict):
                            dt = item[1].get('dt', [])
                            for dt_item in dt:
                                if isinstance(dt_item, list) and len(dt_item) >= 2:
                                    if dt_item[0] == 'text' and not result['definition']:
                                        result['definition'] = self._clean_mw_text(dt_item[1])
                                    elif dt_item[0] == 'vis':
                                        for vis in dt_item[1]:
                                            if isinstance(vis, dict) and vis.get('t'):
                                                sent = self._clean_mw_text(vis['t'])
                                                if sent and sent not in result['sentences']:
                                                    result['sentences'].append(sent)
            
            # Parse phrases/idioms (dros - defined run-ons)
            for dro in entry.get('dros', []):
                if isinstance(dro, dict) and dro.get('drp'):
                    phrase = self._clean_mw_text(dro['drp'])
                    if phrase:
                        result['idioms'].append(phrase)
            
            return result
            
        except Exception as e:
            if self.test_mode:
                self.api_responses[f'mw_learners_{word}'] = {
                    'url': f"{URLS['mw_learners']}/{word}",
                    'error': str(e)
                }
            self.issues.api_errors.append({
                'source': 'MW_Learners',
                'word': word,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            return None
    
    def _clean_mw_text(self, text: str) -> str:
        """Clean MW markup from text."""
        import re
        
        if not text:
            return ""
        
        text = re.sub(r'\{bc\}', '', text)
        text = re.sub(r'\{it\}([^{]*)\{/it\}', r'\1', text)
        text = re.sub(r'\{b\}([^{]*)\{/b\}', r'\1', text)
        text = re.sub(r'\{inf\}([^{]*)\{/inf\}', r'\1', text)
        text = re.sub(r'\{sup\}([^{]*)\{/sup\}', r'\1', text)
        text = re.sub(r'\{ldquo\}', '"', text)
        text = re.sub(r'\{rdquo\}', '"', text)
        text = re.sub(r'\{phrase\}([^{]*)\{/phrase\}', r'\1', text)
        text = re.sub(r'\{wi\}([^{]*)\{/wi\}', r'\1', text)
        text = re.sub(r'\{gloss\}([^{]*)\{/gloss\}', r'\1', text)
        text = re.sub(r'\{dx\}.*?\{/dx\}', '', text)
        text = re.sub(r'\{dx_def\}.*?\{/dx_def\}', '', text)
        text = re.sub(r'\{dx_ety\}.*?\{/dx_ety\}', '', text)
        text = re.sub(r'\{a_link\|([^}]*)\}', r'\1', text)
        text = re.sub(r'\{d_link\|([^|]*)\|[^}]*\}', r'\1', text)
        text = re.sub(r'\{sx\|([^|]*)\|[^}]*\}', r'\1', text)
        text = re.sub(r'\{[^}]+\}', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _fetch_datamuse_category(self, word: str) -> str:
        """Fetch category from Datamuse using rel_gen (generalization)."""
        try:
            url = f"{URLS['datamuse']}?rel_gen={word}&max=3"
            resp = requests.get(url, timeout=10)
            
            # Always log API response in test mode
            if self.test_mode:
                try:
                    response_data = resp.json() if resp.status_code == 200 else resp.text[:500]
                except:
                    response_data = resp.text[:500]
                    
                self.api_responses[f'datamuse_category_{word}'] = {
                    'url': url,
                    'status': resp.status_code,
                    'response': response_data
                }
            
            if resp.status_code != 200:
                self.issues.api_errors.append({
                    'source': 'Datamuse_category',
                    'word': word,
                    'status': resp.status_code,
                    'timestamp': datetime.now().isoformat()
                })
                return ''
            
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                return data[0].get('word', '')
            
            return ''
            
        except Exception as e:
            if self.test_mode:
                self.api_responses[f'datamuse_category_{word}'] = {
                    'url': f"{URLS['datamuse']}?rel_gen={word}&max=3",
                    'error': str(e)
                }
            self.issues.api_errors.append({
                'source': 'Datamuse_category',
                'word': word,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            return ''
    
    def _fetch_datamuse_rhymes(self, word: str) -> List[str]:
        """Fetch rhymes from Datamuse."""
        try:
            url = f"{URLS['datamuse']}?rel_rhy={word}&max=10"
            resp = requests.get(url, timeout=10)
            
            # Always log API response in test mode
            if self.test_mode:
                try:
                    response_data = resp.json() if resp.status_code == 200 else resp.text[:500]
                except:
                    response_data = resp.text[:500]
                    
                self.api_responses[f'datamuse_rhymes_{word}'] = {
                    'url': url,
                    'status': resp.status_code,
                    'response': response_data
                }
            
            if resp.status_code != 200:
                self.issues.api_errors.append({
                    'source': 'Datamuse_rhymes',
                    'word': word,
                    'status': resp.status_code,
                    'timestamp': datetime.now().isoformat()
                })
                return []
            
            data = resp.json()
            rhymes = []
            for item in data:
                w = item.get('word', '')
                if w and ' ' not in w and w.isalpha():
                    rhymes.append(w)
            
            return rhymes[:7]
            
        except Exception as e:
            if self.test_mode:
                self.api_responses[f'datamuse_rhymes_{word}'] = {
                    'url': f"{URLS['datamuse']}?rel_rhy={word}&max=10",
                    'error': str(e)
                }
            self.issues.api_errors.append({
                'source': 'Datamuse_rhymes',
                'word': word,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            return []
    
    def _get_wordnet_category(self, word: str, pos: str) -> str:
        """Get category from WordNet using hypernyms."""
        if not WORDNET_AVAILABLE:
            if self.test_mode:
                self.api_responses[f'wordnet_{word}'] = {
                    'source': 'WordNet',
                    'error': 'WordNet not available (NLTK data not downloaded)',
                    'skipped': True
                }
                self.issues.api_errors.append({
                    'source': 'WordNet',
                    'word': word,
                    'error': 'WordNet not available',
                    'timestamp': datetime.now().isoformat()
                })
            return ''
        
        try:
            # Map POS to WordNet POS
            pos_map = {
                'noun': wn.NOUN,
                'verb': wn.VERB,
                'adjective': wn.ADJ,
            }
            wn_pos = pos_map.get(pos)
            
            if not wn_pos:
                if self.test_mode:
                    self.api_responses[f'wordnet_{word}'] = {
                        'source': 'WordNet',
                        'word': word,
                        'pos': pos,
                        'error': f'POS "{pos}" not mapped to WordNet',
                        'result': None
                    }
                return ''
            
            synsets = wn.synsets(word, pos=wn_pos)
            
            if self.test_mode:
                self.api_responses[f'wordnet_{word}'] = {
                    'source': 'WordNet',
                    'word': word,
                    'pos': pos,
                    'synsets_found': len(synsets),
                    'synsets': [str(s) for s in synsets[:3]] if synsets else [],
                }
            
            if not synsets:
                return ''
            
            # Get hypernyms of first synset
            hypernyms = synsets[0].hypernyms()
            
            if self.test_mode:
                self.api_responses[f'wordnet_{word}']['hypernyms'] = [str(h) for h in hypernyms[:3]] if hypernyms else []
            
            if hypernyms:
                # Get the name of the first hypernym
                result = hypernyms[0].lemmas()[0].name().replace('_', ' ')
                if self.test_mode:
                    self.api_responses[f'wordnet_{word}']['result'] = result
                return result
            
            return ''
            
        except Exception as e:
            if self.test_mode:
                self.api_responses[f'wordnet_{word}'] = {
                    'source': 'WordNet',
                    'word': word,
                    'error': str(e)
                }
            self.issues.api_errors.append({
                'source': 'WordNet',
                'word': word,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            return ''
    
    def _merge_synonyms_antonyms(self, oxford_list: List[str], mw_list: List[str]) -> List[str]:
        """Merge Oxford and MW lists, removing duplicates."""
        result = []
        seen = set()
        
        # Add Oxford entries first
        for item in oxford_list:
            if item.lower() not in seen:
                result.append(item)
                seen.add(item.lower())
        
        # Add MW entries
        for item in mw_list:
            if item.lower() not in seen:
                result.append(item)
                seen.add(item.lower())
        
        return result[:5]  # Limit to 5
    
    def generate_entry(self, word_data: Dict) -> Optional[WordEntry]:
        """
        Generate a complete wordbank entry for a word.
        
        Args:
            word_data: Dict with word, pos, definition, synonyms, antonyms from Oxford
            
        Returns:
            WordEntry or None if generation fails
        """
        word = word_data['word']
        pos = word_data['pos']
        oxford_definition = word_data['definition']
        oxford_synonyms = word_data['synonyms']
        oxford_antonyms = word_data['antonyms']
        
        print(f"   Processing: {word} ({pos})")
        
        entry = WordEntry(
            id=word.lower(),
            word=word,
            partOfSpeech=pos,
        )
        
        # 1. Get definition, sentences, idioms from MW Learner's (or use Oxford)
        mw_data = self._fetch_mw_learners(word)
        time.sleep(API_DELAY)
        
        if mw_data and mw_data.get('definition'):
            entry.definition = mw_data['definition']
            entry.sentences = mw_data.get('sentences', [])[:3]
            entry.phrases = mw_data.get('idioms', [])[:5]
            entry.sources['definition'] = 'merriam_webster'
            entry.sources['sentences'] = 'merriam_webster'
            entry.sources['phrases'] = 'merriam_webster'
        else:
            # Fall back to Oxford definition
            entry.definition = oxford_definition
            entry.sources['definition'] = 'oxford_3000'
        
        if not entry.definition:
            self.issues.words_without_definition.append(word)
            return None
        
        # 2. Get synonyms and antonyms (merge Oxford + MW)
        mw_thesaurus = self._fetch_mw_thesaurus(word)
        time.sleep(API_DELAY)
        
        entry.synonyms = self._merge_synonyms_antonyms(oxford_synonyms, mw_thesaurus.get('synonyms', []))
        entry.antonyms = self._merge_synonyms_antonyms(oxford_antonyms, mw_thesaurus.get('antonyms', []))
        entry.sources['synonyms'] = 'oxford_3000+merriam_webster_thesaurus'
        entry.sources['antonyms'] = 'oxford_3000+merriam_webster_thesaurus'
        
        if not entry.synonyms:
            self.issues.words_without_synonyms.append(word)
        if not entry.antonyms:
            self.issues.words_without_antonyms.append(word)
        
        # 3. Get associated words from USF
        entry.associated = self._fetch_associated_words(word)
        entry.sources['associated'] = 'usf_free_association'
        
        if not entry.associated:
            self.issues.words_without_associated.append(word)
        
        # 4. Get rhymes from Datamuse
        entry.rhymes = self._fetch_datamuse_rhymes(word)
        entry.sources['rhymes'] = 'datamuse'
        time.sleep(API_DELAY)
        
        # 5. Find emoji with fallback strategy
        emoji, emoji_category, emoji_source = self._find_emoji(word, entry.synonyms)
        entry.emoji = emoji
        entry.sources['emoji'] = emoji_source if emoji else 'not_found'
        
        if not emoji:
            self.issues.words_without_emoji.append(word)
        
        # 6. Get categories (array with multiple sources)
        categories = []
        
        # BehrouzSohrabi category (from emoji)
        if emoji_category:
            categories.append({'source': 'BehrouzSohrabi', 'category': emoji_category})
        
        # Datamuse category
        if pos == 'noun':
            datamuse_cat = self._fetch_datamuse_category(word)
            if datamuse_cat:
                categories.append({'source': 'Datamuse', 'category': datamuse_cat})
            time.sleep(API_DELAY)
        
        # WordNet category
        wordnet_cat = self._get_wordnet_category(word, pos)
        if wordnet_cat:
            categories.append({'source': 'WordNet', 'category': wordnet_cat})
        
        # Store categories as array
        entry.category = categories if categories else []
        entry.sources['category'] = 'BehrouzSohrabi+Datamuse+WordNet'
        
        if not categories:
            self.issues.words_without_categories.append(word)
        
        # 7. Get sound group
        entry.soundGroup = self.sound_detector.get_sound_group(word)
        
        # 8. Mark review status
        entry.needsReview = not entry.emoji or not entry.definition
        
        return entry
    
    def generate_wordbank(self, output_path: str = None) -> Tuple[List[Dict], IssueReport]:
        """
        Generate wordbank from Oxford 3000 words.
        
        Args:
            output_path: Optional path to save the wordbank JSON
            
        Returns:
            Tuple of (list of entry dicts, IssueReport)
        """
        print("\n" + "=" * 60)
        print("📚 Oxford 3000 Wordbank Generation")
        print("=" * 60)
        
        # Load emoji data
        self._fetch_emoji_data()
        
        # Load Oxford 3000
        oxford_words = self.load_oxford_3000()
        
        # In test mode, limit to first N words
        if self.test_mode:
            oxford_words = oxford_words[:self.test_word_count]
            print(f"\n🧪 TEST MODE: Processing {len(oxford_words)} words")
        
        entries = []
        
        print(f"\n🔄 Processing {len(oxford_words)} words...")
        
        for i, word_data in enumerate(oxford_words):
            print(f"\n[{i+1}/{len(oxford_words)}]", end='')
            
            entry = self.generate_entry(word_data)
            
            if entry:
                entry_dict = entry.to_dict()
                # Convert category to array format in the output
                if isinstance(entry.category, list):
                    entry_dict['category'] = entry.category
                entries.append(entry_dict)
        
        print(f"\n\n✅ Generated {len(entries)} entries")
        
        # Create wordbank structure
        wordbank = {
            "version": "3.0",
            "language": "en",
            "generatedAt": datetime.now().isoformat(),
            "generationMethod": "oxford_3000",
            "totalEntries": len(entries),
            "words": entries,
        }
        
        # Save wordbank if path provided
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(wordbank, f, indent=2, ensure_ascii=False)
            print(f"💾 Saved wordbank to {output_path}")
        
        # Save API responses in test mode
        if self.test_mode:
            api_log_path = DATA_DIR / "test_api_responses.json"
            with open(api_log_path, 'w', encoding='utf-8') as f:
                json.dump(self.api_responses, f, indent=2, ensure_ascii=False)
            print(f"📋 Saved API responses to {api_log_path}")
        
        # Save issues report
        issues_path = DATA_DIR / "generation_issues_report.json"
        with open(issues_path, 'w', encoding='utf-8') as f:
            json.dump(self.issues.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"📋 Saved issues report to {issues_path}")
        
        return entries, self.issues


def run_test_generation():
    """Run test generation with 10 words."""
    generator = OxfordWordbankGenerator(test_mode=True, test_word_count=10)
    output_path = DATA_DIR / "test_wordbank_oxford.json"
    
    entries, issues = generator.generate_wordbank(str(output_path))
    
    print("\n" + "=" * 60)
    print("📊 Test Generation Summary")
    print("=" * 60)
    print(f"Total entries generated: {len(entries)}")
    print(f"Words without emoji: {len(issues.words_without_emoji)}")
    print(f"Words without definition: {len(issues.words_without_definition)}")
    print(f"Words without associated: {len(issues.words_without_associated)}")
    print(f"Words without categories: {len(issues.words_without_categories)}")
    print(f"API errors: {len(issues.api_errors)}")
    
    return entries, issues


if __name__ == "__main__":
    run_test_generation()

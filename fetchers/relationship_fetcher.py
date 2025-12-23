"""
Relationship fetcher for synonyms, antonyms, rhymes, and associations.

API Sources:
- Merriam-Webster Intermediate Thesaurus: Synonyms and Antonyms
- Datamuse API: Rhymes only
- USF Free Association Norms: Associated words (local CSV files)

Key features:
- High-quality synonyms/antonyms from MW Thesaurus
- Falls back to Free Dictionary when MW is unavailable
- Uses local USF Free Association data for associations (no API calls)
- Filters out domain-specific and obscure terms
"""

import re
import csv
import time
import requests
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from datetime import datetime, timedelta

from ..config import (
    URLS, API_DELAY, EXCLUDED_WORDS, MERRIAM_WEBSTER_THESAURUS_KEY,
    FREE_ASSOCIATION_DIR, USF_FILE_MAPPING, RATE_LIMITS
)
from ..utils.cache import cache_get, cache_set


class RelationshipFetcher:
    """
    Fetches word relationships from multiple sources.
    
    - Synonyms/Antonyms: Merriam-Webster Intermediate Thesaurus
    - Rhymes: Datamuse API
    - Associations: USF Free Association Norms (local files)
    """
    
    # Domain-specific words to filter out
    DOMAIN_SPECIFIC_WORDS = {
        'rbi', 'runs', 'batting', 'pitcher', 'inning', 'dugout',
        'wicket', 'bowler', 'batsman', 'crease', 'stumps',
        'boolean', 'integer', 'string', 'array', 'algorithm',
        'seizure', 'syndrome', 'disorder', 'diagnosis',
        'plaintiff', 'defendant', 'litigation', 'tort',
        'heraldic', 'ecclesiastical', 'liturgical', 'canonical',
    }
    
    # Obscure words to filter out
    OBSCURE_WORDS = {
        'entropy', 'varlet', 'befree', 'newsworthiness',
        'nonpareil', 'bender', 'cardinal',
    }
    
    # Strong synonym pairs (verified high-quality relationships)
    STRONG_SYNONYM_PAIRS = {
        'best': ['optimal', 'finest', 'greatest', 'supreme', 'top'],
        'worst': ['poorest', 'lowest', 'bottom'],
        'good': ['fine', 'excellent', 'great', 'pleasant', 'positive'],
        'bad': ['poor', 'terrible', 'awful', 'unpleasant', 'negative'],
        'big': ['large', 'huge', 'enormous', 'massive', 'giant'],
        'small': ['little', 'tiny', 'minute', 'miniature', 'compact'],
        'happy': ['joyful', 'cheerful', 'glad', 'pleased', 'content'],
        'sad': ['unhappy', 'sorrowful', 'melancholy', 'depressed', 'gloomy'],
        'fast': ['quick', 'rapid', 'swift', 'speedy'],
        'slow': ['sluggish', 'gradual', 'leisurely', 'unhurried'],
    }
    
    # Strong antonym pairs
    STRONG_ANTONYM_PAIRS = {
        'best': ['worst'],
        'good': ['bad', 'evil', 'poor'],
        'big': ['small', 'little', 'tiny'],
        'happy': ['sad', 'unhappy', 'miserable'],
        'fast': ['slow'],
        'hot': ['cold', 'cool', 'freezing'],
        'old': ['new', 'young', 'modern'],
        'beautiful': ['ugly', 'hideous'],
        'strong': ['weak', 'feeble'],
        'rich': ['poor'],
        'true': ['false'],
        'open': ['closed', 'shut'],
        'light': ['dark', 'heavy'],
    }
    
    def __init__(self, quality_mode: str = "strict"):
        """
        Initialize relationship fetcher.
        
        Args:
            quality_mode: "strict" for fewer but better results
        """
        self.quality_mode = quality_mode
        self.cache: Dict[str, Dict] = {}
        
        # Rate limit tracking for MW Thesaurus
        self._mw_available = True
        self._mw_rate_limited = False
        self._requests_today = 0
        self._day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self._requests_this_minute = 0
        self._minute_start = time.time()
        
        # USF data cache
        self._usf_data: Dict[str, Dict[str, List[Tuple[str, int]]]] = {}
        self._usf_loaded: Set[str] = set()
    
    def _is_valid_related_word(self, word: str, target_word: str) -> bool:
        """Check if a word is a valid synonym/antonym."""
        if not word:
            return False
        
        word = word.strip().lower()
        
        if len(word) < 2:
            return False
        if ' ' in word:
            return False
        if not word.isalpha():
            return False
        if word == target_word.lower():
            return False
        if word in self.OBSCURE_WORDS:
            return False
        if word in self.DOMAIN_SPECIFIC_WORDS:
            return False
        if word in EXCLUDED_WORDS:
            return False
        if len(word) < 3:
            return False
        
        return True
    
    def _check_rate_limits(self) -> bool:
        """Check MW Thesaurus rate limits."""
        now = time.time()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        if today > self._day_start:
            self._requests_today = 0
            self._day_start = today
            self._mw_rate_limited = False
        
        if now - self._minute_start > 60:
            self._requests_this_minute = 0
            self._minute_start = now
        
        per_minute = RATE_LIMITS['merriam_webster']['requests_per_minute']
        per_day = RATE_LIMITS['merriam_webster']['requests_per_day']
        
        if self._requests_this_minute >= per_minute:
            return False
        if self._requests_today >= per_day:
            return False
        
        return True
    
    def _record_request(self):
        """Record a Thesaurus API request."""
        self._requests_this_minute += 1
        self._requests_today += 1
    
    def fetch_all(self, word: str) -> Dict[str, List[str]]:
        """
        Fetch all relationships for a word.
        
        Returns dict with:
            - synonyms: from MW Thesaurus
            - antonyms: from MW Thesaurus
            - associated: from USF Free Association Norms
            - rhymes: from Datamuse
        """
        word_lower = word.lower().strip()
        
        # Check cache
        cache_key = f"relationships_v5_{word_lower}_{self.quality_mode}"
        cached = cache_get(cache_key)
        if cached:
            return cached
        
        result = {
            'synonyms': [],
            'antonyms': [],
            'associated': [],
            'rhymes': [],
        }
        
        # Get curated synonyms/antonyms first
        curated_synonyms = self.STRONG_SYNONYM_PAIRS.get(word_lower, [])
        curated_antonyms = self.STRONG_ANTONYM_PAIRS.get(word_lower, [])
        
        # Fetch synonyms/antonyms from MW Thesaurus
        if MERRIAM_WEBSTER_THESAURUS_KEY and self._check_rate_limits():
            mw_result = self._fetch_from_mw_thesaurus(word_lower)
            if mw_result:
                # Merge curated + API (curated first)
                all_synonyms = curated_synonyms.copy()
                for syn in mw_result.get('synonyms', []):
                    if syn.lower() not in [s.lower() for s in all_synonyms]:
                        all_synonyms.append(syn)
                result['synonyms'] = all_synonyms[:5]
                
                all_antonyms = curated_antonyms.copy()
                for ant in mw_result.get('antonyms', []):
                    if ant.lower() not in [a.lower() for a in all_antonyms]:
                        all_antonyms.append(ant)
                result['antonyms'] = all_antonyms[:5]
        else:
            # Fall back to Free Dictionary
            fd_result = self._fetch_from_free_dictionary(word_lower)
            if fd_result:
                all_synonyms = curated_synonyms.copy()
                for syn in fd_result.get('synonyms', []):
                    if syn.lower() not in [s.lower() for s in all_synonyms]:
                        all_synonyms.append(syn)
                result['synonyms'] = all_synonyms[:5]
                
                all_antonyms = curated_antonyms.copy()
                for ant in fd_result.get('antonyms', []):
                    if ant.lower() not in [a.lower() for a in all_antonyms]:
                        all_antonyms.append(ant)
                result['antonyms'] = all_antonyms[:5]
            else:
                result['synonyms'] = curated_synonyms[:5]
                result['antonyms'] = curated_antonyms[:5]
        
        time.sleep(API_DELAY)
        
        # Fetch associated words from USF Free Association Norms
        result['associated'] = self._fetch_usf_associations(word_lower)[:6]
        
        time.sleep(API_DELAY)
        
        # Fetch rhymes from Datamuse
        result['rhymes'] = self._fetch_rhymes(word_lower)
        
        # Cache and return
        cache_set(cache_key, result)
        
        return result
    
    def _fetch_from_mw_thesaurus(self, word: str) -> Optional[Dict]:
        """
        Fetch synonyms/antonyms from Merriam-Webster Intermediate Thesaurus.
        
        MW Thesaurus format:
        - meta.syns: list of synonym groups
        - meta.ants: list of antonym groups
        """
        if not MERRIAM_WEBSTER_THESAURUS_KEY:
            return None
        
        try:
            url = f"{URLS['mw_thesaurus']}/{word}"
            params = {'key': MERRIAM_WEBSTER_THESAURUS_KEY}
            
            resp = requests.get(url, params=params, timeout=10)
            self._record_request()
            
            if resp.status_code != 200:
                if resp.status_code == 429:
                    self._mw_rate_limited = True
                return None
            
            data = resp.json()
            
            if not data:
                return None
            
            # MW returns list of strings if word not found
            if isinstance(data[0], str):
                return None
            
            result = {
                'synonyms': [],
                'antonyms': [],
            }
            
            # Get synonyms and antonyms from first entry
            entry = data[0]
            
            if isinstance(entry, dict):
                meta = entry.get('meta', {})
                
                # Synonyms are in meta.syns (list of lists)
                syns = meta.get('syns', [])
                for syn_group in syns:
                    for syn in syn_group:
                        if self._is_valid_related_word(syn, word):
                            if syn.lower() not in [s.lower() for s in result['synonyms']]:
                                result['synonyms'].append(syn)
                
                # Antonyms are in meta.ants (list of lists)
                ants = meta.get('ants', [])
                for ant_group in ants:
                    for ant in ant_group:
                        if self._is_valid_related_word(ant, word):
                            if ant.lower() not in [a.lower() for a in result['antonyms']]:
                                result['antonyms'].append(ant)
            
            return result
            
        except Exception as e:
            return None
    
    def _fetch_from_free_dictionary(self, word: str) -> Optional[Dict]:
        """Fetch synonyms/antonyms from Free Dictionary (fallback)."""
        try:
            url = f"{URLS['free_dictionary']}/{word}"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            if not data or not isinstance(data, list):
                return None
            
            result = {
                'synonyms': [],
                'antonyms': [],
            }
            
            entry = data[0]
            
            for meaning in entry.get('meanings', []):
                # Definition-level synonyms/antonyms
                for defn in meaning.get('definitions', []):
                    for syn in defn.get('synonyms', []):
                        if self._is_valid_related_word(syn, word):
                            if syn.lower() not in [s.lower() for s in result['synonyms']]:
                                result['synonyms'].append(syn)
                    
                    for ant in defn.get('antonyms', []):
                        if self._is_valid_related_word(ant, word):
                            if ant.lower() not in [a.lower() for a in result['antonyms']]:
                                result['antonyms'].append(ant)
                
                # Meaning-level synonyms/antonyms
                for syn in meaning.get('synonyms', []):
                    if self._is_valid_related_word(syn, word):
                        if syn.lower() not in [s.lower() for s in result['synonyms']]:
                            result['synonyms'].append(syn)
                
                for ant in meaning.get('antonyms', []):
                    if self._is_valid_related_word(ant, word):
                        if ant.lower() not in [a.lower() for a in result['antonyms']]:
                            result['antonyms'].append(ant)
            
            return result
            
        except Exception as e:
            return None
    
    def _load_usf_file(self, first_letter: str) -> None:
        """
        Load USF Free Association Norms file for a letter.
        
        Files contain columns:
        CUE, TARGET, NORMED?, #G, #P, FSG, BSG, MSG, OSG, ...
        
        We use #G (number of participants who gave this response) for ranking.
        """
        first_letter = first_letter.upper()
        
        if first_letter in self._usf_loaded:
            return
        
        if first_letter not in USF_FILE_MAPPING:
            self._usf_loaded.add(first_letter)
            return
        
        filename = USF_FILE_MAPPING[first_letter]
        filepath = FREE_ASSOCIATION_DIR / filename
        
        if not filepath.exists():
            print(f"   ⚠ USF file not found: {filepath}")
            self._usf_loaded.add(first_letter)
            return
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    cue = row.get('CUE', '').strip().upper()
                    target = row.get('TARGET', '').strip()
                    
                    # Get #G count (number of participants)
                    try:
                        g_count = int(row.get('#G', '0').strip())
                    except (ValueError, TypeError):
                        g_count = 0
                    
                    if not cue or not target or g_count == 0:
                        continue
                    
                    # Skip multi-word targets
                    if ' ' in target:
                        continue
                    
                    if cue not in self._usf_data:
                        self._usf_data[cue] = []
                    
                    self._usf_data[cue].append((target.lower(), g_count))
            
            self._usf_loaded.add(first_letter)
            
        except Exception as e:
            print(f"   ⚠ Error loading USF file {filepath}: {e}")
            self._usf_loaded.add(first_letter)
    
    def _fetch_usf_associations(self, word: str) -> List[str]:
        """
        Fetch associated words from USF Free Association Norms.
        
        Returns top 3-5 words with highest #G count.
        """
        word_upper = word.upper()
        first_letter = word_upper[0] if word_upper else ''
        
        # Load the relevant file
        self._load_usf_file(first_letter)
        
        # Get associations
        associations = self._usf_data.get(word_upper, [])
        
        if not associations:
            return []
        
        # Sort by #G count (descending) and take top 3-5
        sorted_assoc = sorted(associations, key=lambda x: x[1], reverse=True)
        
        # Filter and validate
        result = []
        for target, g_count in sorted_assoc:
            if self._is_valid_related_word(target, word):
                if target not in result:
                    result.append(target)
                if len(result) >= 5:
                    break
        
        return result[:5] if len(result) >= 3 else result[:3]
    
    def _fetch_rhymes(self, word: str) -> List[str]:
        """
        Fetch rhyming words from Datamuse API.
        
        Filters to single words only.
        """
        try:
            url = f"{URLS['datamuse']}?rel_rhy={word}&max=30"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            
            # Filter to single words
            single_words = []
            
            for item in data:
                w = item.get('word', '')
                if not w:
                    continue
                
                # Skip phrases
                if ' ' in w:
                    continue
                
                # Validate
                if w.isalpha() and len(w) >= 2:
                    single_words.append(w)
            
            return single_words[:7]
            
        except Exception as e:
            return []
    
    def fetch_synonyms(self, word: str, limit: int = 5) -> List[str]:
        """Fetch only synonyms."""
        result = self.fetch_all(word)
        return result.get('synonyms', [])[:limit]
    
    def fetch_antonyms(self, word: str, limit: int = 5) -> List[str]:
        """Fetch only antonyms."""
        result = self.fetch_all(word)
        return result.get('antonyms', [])[:limit]
    
    def fetch_rhymes(self, word: str, limit: int = 7) -> List[str]:
        """Fetch only rhymes."""
        return self._fetch_rhymes(word.lower())[:limit]
    
    def fetch_associated(self, word: str, limit: int = 6) -> List[str]:
        """Fetch only associated words."""
        return self._fetch_usf_associations(word.lower())[:limit]
    
    def set_quality_mode(self, mode: str):
        """Set quality mode."""
        if mode in ("strict", "standard"):
            self.quality_mode = mode
    
    def get_status(self) -> Dict:
        """Get API status information."""
        return {
            'mw_thesaurus_available': self._mw_available,
            'mw_rate_limited': self._mw_rate_limited,
            'usf_files_loaded': list(self._usf_loaded),
            'usf_cues_loaded': len(self._usf_data),
        }

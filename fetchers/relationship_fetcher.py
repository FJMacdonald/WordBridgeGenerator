"""
Relationship fetcher for synonyms, antonyms, rhymes, and associations.

Uses Datamuse API for:
- Synonyms (rel_syn)
- Antonyms (rel_ant)
- Associated/triggered words (rel_trg) - with filtering for relevance
- Rhymes (rel_rhy)
"""

import re
import time
import requests
from typing import Dict, List, Set

from ..config import URLS, API_DELAY, EXCLUDED_WORDS
from ..utils.cache import cache_get, cache_set


class RelationshipFetcher:
    """
    Fetches word relationships from Datamuse API.
    
    Features:
    - Filters rhymes to single words only
    - Filters associations to remove irrelevant/domain-specific results
    - Validates that related words are common English words
    """
    
    # Words that indicate domain-specific associations to filter out
    DOMAIN_SPECIFIC_WORDS = {
        # Baseball terms (often associated with "home", "run", etc.)
        'rbi', 'runs', 'bats', 'batting', 'pitched', 'pitcher', 'inning',
        'innings', 'dugout', 'outfield', 'infield', 'shortstop', 'catcher',
        'umpire', 'strikeout', 'homerun', 'ballpark', 'fastball', 'curveball',
        
        # Cricket terms
        'wicket', 'bowler', 'batsman', 'crease', 'innings', 'stumps',
        
        # Technical/computing terms
        'boolean', 'integer', 'string', 'array', 'function', 'variable',
        'algorithm', 'database', 'server', 'client', 'protocol', 'syntax',
        
        # Medical terms
        'seizure', 'syndrome', 'disorder', 'diagnosis', 'prognosis',
        'symptom', 'pathology', 'etiology', 'lesion', 'tumor',
        
        # Legal terms
        'plaintiff', 'defendant', 'litigation', 'tort', 'statute',
        'jurisdiction', 'deposition', 'subpoena', 'affidavit',
        
        # Other domain-specific
        'heraldic', 'ecclesiastical', 'liturgical', 'canonical',
    }
    
    def __init__(self):
        self.cache: Dict[str, Dict] = {}
    
    def fetch_all(self, word: str) -> Dict[str, List[str]]:
        """
        Fetch all relationships for a word.
        
        Returns dict with:
            - synonyms: list of synonyms
            - antonyms: list of antonyms
            - associated: list of associated words
            - rhymes: list of rhyming words (single words only)
        """
        word_lower = word.lower().strip()
        
        # Check cache
        cache_key = f"relationships_v2_{word_lower}"
        cached = cache_get(cache_key)
        if cached:
            return cached
        
        result = {
            'synonyms': [],
            'antonyms': [],
            'associated': [],
            'rhymes': [],
        }
        
        # Fetch synonyms
        result['synonyms'] = self._fetch_relation(word, 'rel_syn', 10)[:5]
        
        time.sleep(API_DELAY)
        
        # Fetch antonyms
        result['antonyms'] = self._fetch_relation(word, 'rel_ant', 10)[:5]
        
        time.sleep(API_DELAY)
        
        # Fetch associated words (with domain filtering)
        result['associated'] = self._fetch_relation(word, 'rel_trg', 20, filter_domains=True)[:6]
        
        time.sleep(API_DELAY)
        
        # Fetch rhymes (with filtering)
        result['rhymes'] = self._fetch_rhymes(word)
        
        # Cache and return
        cache_set(cache_key, result)
        
        return result
    
    def _fetch_relation(self, word: str, relation: str, limit: int,
                        filter_domains: bool = False) -> List[str]:
        """
        Fetch a specific relationship type.
        
        Args:
            word: Target word
            relation: Datamuse relation type
            limit: Maximum results to fetch
            filter_domains: If True, filter out domain-specific words
        """
        try:
            url = f"{URLS['datamuse']}?{relation}={word}&max={limit}"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            
            # Extract words with filtering
            words = []
            for item in data:
                w = item.get('word', '').lower()
                
                # Skip multi-word phrases
                if ' ' in w:
                    continue
                
                # Skip excluded words
                if w in EXCLUDED_WORDS:
                    continue
                
                # Skip domain-specific words if filtering is enabled
                if filter_domains and w in self.DOMAIN_SPECIFIC_WORDS:
                    continue
                
                # Skip very short words
                if len(w) < 3:
                    continue
                
                words.append(w)
            
            return words
            
        except Exception as e:
            return []
    
    def _fetch_rhymes(self, word: str) -> List[str]:
        """
        Fetch rhyming words with special filtering.
        
        - Prioritize single-word rhymes
        - Only include phrases if no single words found
        - Maximum 7 rhymes
        """
        try:
            url = f"{URLS['datamuse']}?rel_rhy={word}&max=30"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            
            # Separate single words and phrases
            single_words = []
            phrases = []
            
            for item in data:
                w = item.get('word', '')
                if not w:
                    continue
                
                if ' ' in w:
                    phrases.append(w)
                else:
                    single_words.append(w)
            
            # Return single words if available, otherwise phrases
            if single_words:
                return single_words[:7]
            elif phrases:
                # Only return phrases as last resort
                return phrases[:7]
            else:
                return []
            
        except Exception as e:
            return []
    
    def fetch_synonyms(self, word: str, limit: int = 5) -> List[str]:
        """Fetch only synonyms."""
        return self._fetch_relation(word, 'rel_syn', limit * 2)[:limit]
    
    def fetch_antonyms(self, word: str, limit: int = 5) -> List[str]:
        """Fetch only antonyms."""
        return self._fetch_relation(word, 'rel_ant', limit * 2)[:limit]
    
    def fetch_rhymes(self, word: str, limit: int = 7) -> List[str]:
        """Fetch only rhymes."""
        rhymes = self._fetch_rhymes(word)
        return rhymes[:limit]
    
    def fetch_associated(self, word: str, limit: int = 6) -> List[str]:
        """Fetch only associated words."""
        return self._fetch_relation(word, 'rel_trg', limit * 2)[:limit]

"""
Relationship fetcher for synonyms, antonyms, rhymes, and associations.

Uses Datamuse API for:
- Synonyms (rel_syn)
- Antonyms (rel_ant)
- Associated/triggered words (rel_trg) - with filtering for relevance
- Rhymes (rel_rhy)

Key improvements:
- Validates that synonyms/antonyms are real single words
- Filters out symbols, phrases, and obscure terms
- Filters domain-specific associations
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
    - Ensures synonyms/antonyms are valid single words (not symbols or phrases)
    """
    
    # Words that indicate domain-specific associations to filter out
    DOMAIN_SPECIFIC_WORDS = {
        # Baseball terms (often associated with "home", "run", etc.)
        'rbi', 'runs', 'bats', 'batting', 'pitched', 'pitcher', 'inning',
        'innings', 'dugout', 'outfield', 'infield', 'shortstop', 'catcher',
        'umpire', 'strikeout', 'homerun', 'ballpark', 'fastball', 'curveball',
        
        # Cricket terms
        'wicket', 'bowler', 'batsman', 'crease', 'stumps',
        
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
    
    # Technical/obscure synonyms that should be filtered out
    # These could confuse aphasia patients
    OBSCURE_WORDS = {
        'entropy',      # Technical information theory term
        'varlet',       # Archaic term
        'befree',       # Not standard English
        'newsworthiness',  # Too technical
    }
    
    def __init__(self):
        self.cache: Dict[str, Dict] = {}
    
    def _is_valid_related_word(self, word: str, target_word: str) -> bool:
        """
        Check if a word is a valid synonym/antonym/related word.
        
        Requirements:
        - Must be a single word (no spaces)
        - Must be at least 2 characters
        - Must contain only letters (no symbols like !, ~, ¬)
        - Must not be the same as the target word
        - Must not be in the obscure words list
        - Must not be a domain-specific term
        
        Args:
            word: The potential related word
            target_word: The word we're finding relationships for
            
        Returns:
            True if valid, False otherwise
        """
        if not word:
            return False
        
        word = word.strip().lower()
        
        # Must be at least 2 characters
        if len(word) < 2:
            return False
        
        # Must not contain spaces (single word only)
        if ' ' in word:
            return False
        
        # Must contain only letters (no symbols, numbers, etc.)
        if not word.isalpha():
            return False
        
        # Must not be the same as target
        if word == target_word.lower():
            return False
        
        # Must not be in obscure words list
        if word in self.OBSCURE_WORDS:
            return False
        
        # Must not be in domain-specific list
        if word in self.DOMAIN_SPECIFIC_WORDS:
            return False
        
        # Must not be in excluded words
        if word in EXCLUDED_WORDS:
            return False
        
        # Must be at least 3 characters for synonyms/antonyms
        if len(word) < 3:
            return False
        
        return True
    
    def fetch_all(self, word: str) -> Dict[str, List[str]]:
        """
        Fetch all relationships for a word.
        
        Returns dict with:
            - synonyms: list of synonyms (validated single words)
            - antonyms: list of antonyms (validated single words)
            - associated: list of associated words
            - rhymes: list of rhyming words (single words only)
        """
        word_lower = word.lower().strip()
        
        # Check cache
        cache_key = f"relationships_v3_{word_lower}"
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
        result['synonyms'] = self._fetch_relation(word, 'rel_syn', 15, validate=True)[:5]
        
        time.sleep(API_DELAY)
        
        # Fetch antonyms
        result['antonyms'] = self._fetch_relation(word, 'rel_ant', 15, validate=True)[:5]
        
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
                        filter_domains: bool = False,
                        validate: bool = False) -> List[str]:
        """
        Fetch a specific relationship type.
        
        Args:
            word: Target word
            relation: Datamuse relation type
            limit: Maximum results to fetch
            filter_domains: If True, filter out domain-specific words
            validate: If True, apply strict validation for synonyms/antonyms
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
                
                # Apply validation for synonyms/antonyms
                if validate:
                    if not self._is_valid_related_word(w, word):
                        continue
                else:
                    # Basic filtering for other relation types
                    if w in EXCLUDED_WORDS:
                        continue
                    if len(w) < 3:
                        continue
                
                # Skip domain-specific words if filtering is enabled
                if filter_domains and w in self.DOMAIN_SPECIFIC_WORDS:
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
                    # Validate rhyme
                    if w.isalpha() and len(w) >= 2:
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
        """Fetch only synonyms (validated)."""
        return self._fetch_relation(word, 'rel_syn', limit * 3, validate=True)[:limit]
    
    def fetch_antonyms(self, word: str, limit: int = 5) -> List[str]:
        """Fetch only antonyms (validated)."""
        return self._fetch_relation(word, 'rel_ant', limit * 3, validate=True)[:limit]
    
    def fetch_rhymes(self, word: str, limit: int = 7) -> List[str]:
        """Fetch only rhymes."""
        rhymes = self._fetch_rhymes(word)
        return rhymes[:limit]
    
    def fetch_associated(self, word: str, limit: int = 6) -> List[str]:
        """Fetch only associated words."""
        return self._fetch_relation(word, 'rel_trg', limit * 2, filter_domains=True)[:limit]

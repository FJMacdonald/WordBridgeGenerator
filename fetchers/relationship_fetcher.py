"""
Relationship fetcher for synonyms, antonyms, rhymes, and associations.

Uses Datamuse API for:
- Synonyms (rel_syn)
- Antonyms (rel_ant)
- Associated/triggered words (rel_trg) - with filtering for relevance
- Rhymes (rel_rhy)

Key improvements:
- STRICT quality filtering for synonyms/antonyms
- Semantic similarity scoring to filter weak relationships
- Validates that synonyms/antonyms match the target word's meaning
- Filters out symbols, phrases, and obscure terms
- Filters domain-specific associations
"""

import re
import time
import requests
from typing import Dict, List, Set, Tuple, Optional

from ..config import URLS, API_DELAY, EXCLUDED_WORDS
from ..utils.cache import cache_get, cache_set


class RelationshipFetcher:
    """
    Fetches word relationships from Datamuse API.
    
    Features:
    - STRICT quality filtering - fewer but better synonyms/antonyms
    - Filters rhymes to single words only
    - Filters associations to remove irrelevant/domain-specific results
    - Validates that related words are common English words
    - Ensures synonyms/antonyms are semantically close
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
    
    # Words that are NOT good synonyms/antonyms despite appearing in results
    # These are often related but not semantically equivalent
    WEAK_SYNONYMS = {
        # Grades/qualities that are too different in intensity
        'decent': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'satisfactory': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'adequate': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'acceptable': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'passable': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'tolerable': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'fair': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'moderate': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'mediocre': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        
        # Generic positive words that aren't true synonyms
        'good': {'best', 'excellent', 'perfect', 'outstanding', 'superb', 'optimal'},
        'nice': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        'fine': {'best', 'excellent', 'perfect', 'outstanding', 'superb'},
        
        # Accomplished is more about skills than quality
        'accomplished': {'best', 'good', 'optimal'},
    }
    
    # Words that are NOT good antonyms despite appearing in results
    WEAK_ANTONYMS = {
        # "evil" and "bad" are moral terms, not quality opposites
        'evil': {'best', 'good', 'excellent', 'optimal'},
        'wicked': {'best', 'good', 'excellent', 'optimal'},
        'sinful': {'best', 'good', 'excellent', 'optimal'},
        'immoral': {'best', 'good', 'excellent', 'optimal'},
        
        # "poor" in quality sense is weak antonym for superlatives
        'poor': {'best', 'excellent', 'superb', 'optimal'},
        
        # Made-up or informal words
        'baddest': {'best', 'good', 'excellent'},  # Informal, not standard
    }
    
    # Strong synonym pairs - these are verified high-quality relationships
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
        'hot': ['warm', 'heated', 'burning', 'scorching'],
        'cold': ['cool', 'chilly', 'freezing', 'frigid'],
        'old': ['aged', 'ancient', 'elderly', 'antique'],
        'new': ['fresh', 'recent', 'modern', 'novel', 'current'],
        'beautiful': ['pretty', 'lovely', 'gorgeous', 'stunning', 'attractive'],
        'ugly': ['unattractive', 'hideous', 'unsightly', 'grotesque'],
        'strong': ['powerful', 'mighty', 'robust', 'sturdy', 'tough'],
        'weak': ['feeble', 'frail', 'fragile', 'delicate'],
        'smart': ['intelligent', 'clever', 'bright', 'brilliant', 'wise'],
        'stupid': ['foolish', 'dumb', 'idiotic', 'senseless'],
        'rich': ['wealthy', 'affluent', 'prosperous', 'well-off'],
        'poor': ['impoverished', 'destitute', 'needy', 'penniless'],
        'easy': ['simple', 'effortless', 'straightforward'],
        'hard': ['difficult', 'tough', 'challenging', 'demanding'],
        'love': ['adore', 'cherish', 'treasure', 'worship'],
        'hate': ['despise', 'detest', 'loathe', 'abhor'],
    }
    
    # Strong antonym pairs - verified high-quality opposites
    STRONG_ANTONYM_PAIRS = {
        'best': ['worst'],
        'good': ['bad', 'evil', 'poor'],
        'big': ['small', 'little', 'tiny'],
        'small': ['big', 'large', 'huge'],
        'happy': ['sad', 'unhappy', 'miserable'],
        'sad': ['happy', 'joyful', 'cheerful'],
        'fast': ['slow'],
        'slow': ['fast', 'quick', 'rapid'],
        'hot': ['cold', 'cool', 'freezing'],
        'cold': ['hot', 'warm'],
        'old': ['new', 'young', 'modern'],
        'new': ['old', 'ancient', 'used'],
        'beautiful': ['ugly', 'hideous'],
        'ugly': ['beautiful', 'pretty', 'attractive'],
        'strong': ['weak', 'feeble'],
        'weak': ['strong', 'powerful'],
        'smart': ['stupid', 'dumb', 'foolish'],
        'stupid': ['smart', 'intelligent', 'clever'],
        'rich': ['poor'],
        'poor': ['rich', 'wealthy'],
        'easy': ['hard', 'difficult'],
        'hard': ['easy', 'simple'],
        'love': ['hate'],
        'hate': ['love'],
        'true': ['false'],
        'false': ['true'],
        'right': ['wrong', 'left'],
        'wrong': ['right', 'correct'],
        'up': ['down'],
        'down': ['up'],
        'in': ['out'],
        'out': ['in'],
        'open': ['closed', 'shut'],
        'closed': ['open'],
        'light': ['dark', 'heavy'],
        'dark': ['light', 'bright'],
        'heavy': ['light', 'lightweight'],
        'alive': ['dead'],
        'dead': ['alive', 'living'],
        'full': ['empty'],
        'empty': ['full'],
        'wet': ['dry'],
        'dry': ['wet'],
        'clean': ['dirty'],
        'dirty': ['clean'],
        'loud': ['quiet', 'silent'],
        'quiet': ['loud', 'noisy'],
    }
    
    # Technical/obscure synonyms that should be filtered out
    # These could confuse aphasia patients
    OBSCURE_WORDS = {
        'entropy',      # Technical information theory term
        'varlet',       # Archaic term
        'befree',       # Not standard English
        'newsworthiness',  # Too technical
        'nonpareil',    # Uncommon
        'bender',       # Multiple meanings, confusing
        'cardinal',     # When used as synonym for numbers, confusing
    }
    
    def __init__(self, quality_mode: str = "strict"):
        """
        Initialize relationship fetcher.
        
        Args:
            quality_mode: "strict" for fewer but better results,
                         "standard" for more results
        """
        self.quality_mode = quality_mode
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
    
    def _is_strong_synonym(self, synonym: str, target: str) -> bool:
        """
        Check if a synonym is semantically strong for the target.
        
        This filters out "weak" synonyms that are technically related
        but not close enough in meaning.
        
        Args:
            synonym: The potential synonym
            target: The target word
            
        Returns:
            True if strong synonym, False if weak
        """
        synonym = synonym.lower()
        target = target.lower()
        
        # Check if this is a known weak relationship
        if synonym in self.WEAK_SYNONYMS:
            if target in self.WEAK_SYNONYMS[synonym]:
                return False
        
        # Check if we have verified strong synonyms for target
        if target in self.STRONG_SYNONYM_PAIRS:
            # If we have a curated list, prefer words from it
            # But don't reject words not in it (API might have good ones)
            pass
        
        return True
    
    def _is_strong_antonym(self, antonym: str, target: str) -> bool:
        """
        Check if an antonym is semantically strong for the target.
        
        This filters out "weak" antonyms that are vaguely opposite
        but not true antonyms.
        
        Args:
            antonym: The potential antonym
            target: The target word
            
        Returns:
            True if strong antonym, False if weak
        """
        antonym = antonym.lower()
        target = target.lower()
        
        # Check if this is a known weak relationship
        if antonym in self.WEAK_ANTONYMS:
            if target in self.WEAK_ANTONYMS[antonym]:
                return False
        
        return True
    
    def _get_strong_synonyms(self, word: str) -> List[str]:
        """Get curated strong synonyms if available."""
        return self.STRONG_SYNONYM_PAIRS.get(word.lower(), [])
    
    def _get_strong_antonyms(self, word: str) -> List[str]:
        """Get curated strong antonyms if available."""
        return self.STRONG_ANTONYM_PAIRS.get(word.lower(), [])
    
    def fetch_all(self, word: str) -> Dict[str, List[str]]:
        """
        Fetch all relationships for a word.
        
        Returns dict with:
            - synonyms: list of synonyms (strict quality filtered)
            - antonyms: list of antonyms (strict quality filtered)
            - associated: list of associated words
            - rhymes: list of rhyming words (single words only)
        """
        word_lower = word.lower().strip()
        
        # Check cache
        cache_key = f"relationships_v4_{word_lower}_{self.quality_mode}"
        cached = cache_get(cache_key)
        if cached:
            return cached
        
        result = {
            'synonyms': [],
            'antonyms': [],
            'associated': [],
            'rhymes': [],
        }
        
        # Get curated synonyms first
        curated_synonyms = self._get_strong_synonyms(word_lower)
        curated_antonyms = self._get_strong_antonyms(word_lower)
        
        # Fetch synonyms from API
        api_synonyms = self._fetch_relation(word, 'rel_syn', 20, validate=True, 
                                            filter_weak_synonyms=True)
        
        # Merge curated + API (curated first, then unique API results)
        all_synonyms = curated_synonyms.copy()
        for syn in api_synonyms:
            if syn.lower() not in [s.lower() for s in all_synonyms]:
                all_synonyms.append(syn)
        
        result['synonyms'] = all_synonyms[:5]  # Max 5 synonyms
        
        time.sleep(API_DELAY)
        
        # Fetch antonyms from API
        api_antonyms = self._fetch_relation(word, 'rel_ant', 20, validate=True,
                                           filter_weak_antonyms=True)
        
        # Merge curated + API
        all_antonyms = curated_antonyms.copy()
        for ant in api_antonyms:
            if ant.lower() not in [a.lower() for a in all_antonyms]:
                all_antonyms.append(ant)
        
        result['antonyms'] = all_antonyms[:5]  # Max 5 antonyms
        
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
                        validate: bool = False,
                        filter_weak_synonyms: bool = False,
                        filter_weak_antonyms: bool = False) -> List[str]:
        """
        Fetch a specific relationship type.
        
        Args:
            word: Target word
            relation: Datamuse relation type
            limit: Maximum results to fetch
            filter_domains: If True, filter out domain-specific words
            validate: If True, apply strict validation for synonyms/antonyms
            filter_weak_synonyms: If True, filter out weak synonyms
            filter_weak_antonyms: If True, filter out weak antonyms
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
                score = item.get('score', 0)
                
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
                
                # Apply strict synonym quality filter
                if filter_weak_synonyms:
                    if not self._is_strong_synonym(w, word):
                        continue
                    # In strict mode, require higher score threshold
                    if self.quality_mode == "strict" and score < 1000:
                        continue
                
                # Apply strict antonym quality filter
                if filter_weak_antonyms:
                    if not self._is_strong_antonym(w, word):
                        continue
                    # In strict mode, require higher score threshold
                    if self.quality_mode == "strict" and score < 1000:
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
        """Fetch only synonyms (validated, quality filtered)."""
        word_lower = word.lower()
        
        # Get curated first
        curated = self._get_strong_synonyms(word_lower)
        
        # Then API
        api_results = self._fetch_relation(word, 'rel_syn', limit * 4, 
                                          validate=True, 
                                          filter_weak_synonyms=True)
        
        # Merge
        all_syns = curated.copy()
        for syn in api_results:
            if syn.lower() not in [s.lower() for s in all_syns]:
                all_syns.append(syn)
        
        return all_syns[:limit]
    
    def fetch_antonyms(self, word: str, limit: int = 5) -> List[str]:
        """Fetch only antonyms (validated, quality filtered)."""
        word_lower = word.lower()
        
        # Get curated first
        curated = self._get_strong_antonyms(word_lower)
        
        # Then API
        api_results = self._fetch_relation(word, 'rel_ant', limit * 4,
                                          validate=True,
                                          filter_weak_antonyms=True)
        
        # Merge
        all_ants = curated.copy()
        for ant in api_results:
            if ant.lower() not in [a.lower() for a in all_ants]:
                all_ants.append(ant)
        
        return all_ants[:limit]
    
    def fetch_rhymes(self, word: str, limit: int = 7) -> List[str]:
        """Fetch only rhymes."""
        rhymes = self._fetch_rhymes(word)
        return rhymes[:limit]
    
    def fetch_associated(self, word: str, limit: int = 6) -> List[str]:
        """Fetch only associated words."""
        return self._fetch_relation(word, 'rel_trg', limit * 2, filter_domains=True)[:limit]
    
    def set_quality_mode(self, mode: str):
        """
        Set quality mode.
        
        Args:
            mode: "strict" for fewer but better results,
                  "standard" for more results
        """
        if mode in ("strict", "standard"):
            self.quality_mode = mode

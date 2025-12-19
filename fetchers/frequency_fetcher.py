"""
Word frequency fetcher for prioritizing common words.

Uses google-10000-english from GitHub.
"""

import requests
from typing import Dict, List, Set, Tuple

from ..config import URLS, EXCLUDED_WORDS
from ..utils.cache import cache_get, cache_set


class FrequencyFetcher:
    """
    Fetches and manages word frequency data.
    """
    
    def __init__(self):
        self.words: List[str] = []
        self.word_to_rank: Dict[str, int] = {}
        self._fetched = False
    
    def fetch(self) -> bool:
        """Fetch frequency list."""
        if self._fetched:
            return True
        
        # Check cache
        cached = cache_get("frequency_list_v2")
        if cached:
            self.words = cached.get('words', [])
            self.word_to_rank = cached.get('ranks', {})
            self._fetched = True
            return True
        
        print("📊 Fetching word frequency list...")
        
        try:
            resp = requests.get(URLS['frequency'], timeout=15)
            resp.raise_for_status()
            
            for rank, line in enumerate(resp.text.strip().split('\n'), 1):
                word = line.strip().lower()
                
                # Filter
                if not word or not word.isalpha():
                    continue
                if len(word) < 3:
                    continue
                if word in EXCLUDED_WORDS:
                    continue
                
                if word not in self.word_to_rank:
                    self.words.append(word)
                    self.word_to_rank[word] = rank
            
            # Cache
            cache_set("frequency_list_v2", {
                'words': self.words,
                'ranks': self.word_to_rank,
            })
            
            print(f"   ✓ Loaded {len(self.words)} frequency words")
            self._fetched = True
            return True
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch frequency list: {e}")
            return False
    
    def get_rank(self, word: str) -> int:
        """
        Get frequency rank for a word.
        Lower rank = more frequent.
        Returns 99999 if word not in list.
        """
        if not self._fetched:
            self.fetch()
        return self.word_to_rank.get(word.lower(), 99999)
    
    def get_top_words(self, n: int, exclude: Set[str] = None) -> List[str]:
        """
        Get top N words by frequency, excluding specified words.
        
        Args:
            n: Number of words to return
            exclude: Set of words to exclude
            
        Returns:
            List of words sorted by frequency
        """
        if not self._fetched:
            self.fetch()
        
        exclude = exclude or set()
        exclude_lower = {w.lower() for w in exclude}
        exclude_lower.update(EXCLUDED_WORDS)
        
        result = []
        for word in self.words:
            if word not in exclude_lower:
                result.append(word)
                if len(result) >= n:
                    break
        
        return result
    
    def get_words_by_length(self, length: int, tolerance: int = 0,
                            exclude: Set[str] = None,
                            limit: int = 100) -> List[str]:
        """
        Get frequent words within a length range.
        
        Args:
            length: Target word length
            tolerance: Allowed deviation (±)
            exclude: Words to exclude
            limit: Maximum words to return
            
        Returns:
            List of words within length range, sorted by frequency
        """
        if not self._fetched:
            self.fetch()
        
        exclude = exclude or set()
        exclude_lower = {w.lower() for w in exclude}
        exclude_lower.update(EXCLUDED_WORDS)
        
        min_len = length - tolerance
        max_len = length + tolerance
        
        result = []
        for word in self.words:
            if word in exclude_lower:
                continue
            if min_len <= len(word) <= max_len:
                result.append(word)
                if len(result) >= limit:
                    break
        
        return result
    
    def is_frequent(self, word: str, threshold: int = 5000) -> bool:
        """Check if a word is in the top N frequent words."""
        return self.get_rank(word) <= threshold

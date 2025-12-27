"""
Category fetcher using Datamuse API.

Uses Datamuse rel_gen (generalization) to assign categories to words.
For example, "dog" -> "animal", "apple" -> "fruit"

This provides semantic categories based on hypernym relationships.
"""

import time
import requests
from typing import Optional, List, Dict

from ..config import URLS, API_DELAY
from ..utils.cache import cache_get, cache_set


class CategoryFetcher:
    """
    Fetches semantic categories for words using Datamuse API.
    
    Uses rel_gen (generalization/hypernym) to find the category.
    For nouns, this gives the "type of" relationship:
    - dog -> animal
    - apple -> fruit
    - car -> vehicle
    
    Note: All words are processed uniformly through the API without
    any hardcoded mappings or prioritization.
    """
    
    def __init__(self):
        self.cache: Dict[str, str] = {}
    
    def fetch_category(self, word: str, pos: str = 'noun') -> str:
        """
        Fetch semantic category for a word.
        
        Args:
            word: The word to categorize
            pos: Part of speech (category only meaningful for nouns)
            
        Returns:
            Category string, or empty string if not found
            
        Note: All words are processed uniformly through the API.
        """
        # Categories are only meaningful for nouns
        if pos != 'noun':
            return ''
        
        word_lower = word.lower().strip()
        
        # Check cache
        cache_key = f"category_v2_{word_lower}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        
        # Fetch from Datamuse
        category = self._fetch_from_datamuse(word_lower)
        
        # Cache result
        cache_set(cache_key, category)
        
        return category
    
    def _fetch_from_datamuse(self, word: str) -> str:
        """
        Fetch category from Datamuse using rel_gen (generalization).
        
        rel_gen returns hypernyms (more general terms).
        """
        try:
            url = f"{URLS['datamuse']}?rel_gen={word}&max=5"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return ''
            
            data = resp.json()
            
            if not data:
                return ''
            
            # Get the best category from results
            # Prefer results that match our known priority categories
            # Use the first result from Datamuse (highest score)
            first_result = data[0].get('word', '')
            return first_result if first_result else ''
            
        except Exception as e:
            return ''
    
    def get_category_with_fallback(self, word: str, emoji_category: str = '', 
                                    pos: str = 'noun') -> str:
        """
        Get category - tries Datamuse, then emoji category as-is, no mappings.
        
        Args:
            word: The word to categorize
            emoji_category: Category from emoji fetcher (used as-is if Datamuse fails)
            pos: Part of speech
            
        Returns:
            Category string or empty string
        """
        if pos != 'noun':
            return ''
        
        # Try Datamuse first
        datamuse_category = self.fetch_category(word, pos)
        if datamuse_category:
            return datamuse_category
        
        # Return emoji category as-is (no mapping/normalization)
        return emoji_category if emoji_category else ''

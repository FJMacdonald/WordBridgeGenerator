"""
Idiom/phrase fetcher.

Source: Merriam-Webster Learner's Dictionary API (dros - defined run-ons)

Note: This module no longer searches local idiom files.
All phrases/idioms come from the MW Learner's Dictionary API,
which provides high-quality, curated phrases for each word.

The phrases are already fetched as part of the dictionary_fetcher
and included in the definition response.
"""

from typing import List, Dict, Optional

from ..utils.cache import cache_get, cache_set


class IdiomFetcher:
    """
    Idiom/phrase fetcher.
    
    Note: Phrases are now fetched from MW Learner's Dictionary API
    as part of the definition fetch. This class provides a minimal
    interface for backward compatibility.
    
    The actual phrase fetching happens in DictionaryFetcher._parse_mw_phrases()
    """
    
    def __init__(self):
        """Initialize idiom fetcher."""
        pass
    
    def fetch_idioms(self, word: str, language: str = 'en', 
                     use_web: bool = True) -> List[str]:
        """
        Fetch idioms for a word.
        
        Note: This is now a pass-through method. Phrases are fetched
        from MW Learner's Dictionary as part of the main definition fetch.
        
        Args:
            word: Target word
            language: Language code (only 'en' supported)
            use_web: Ignored (MW API always used)
            
        Returns:
            Empty list (phrases come from dictionary_fetcher)
        """
        # Phrases are now included in the dictionary response
        # This method exists for backward compatibility
        return []
    
    def search_idiom_file(self, word: str, language: str = 'en') -> List[str]:
        """
        Search idiom file (deprecated).
        
        Note: Local idiom files are no longer used.
        All phrases come from MW Learner's Dictionary.
        
        Returns:
            Empty list
        """
        return []
    
    def add_idiom_to_file(self, idiom: str, language: str = 'en') -> bool:
        """
        Add idiom to file (deprecated).
        
        Note: Local idiom files are no longer used.
        
        Returns:
            False (not supported)
        """
        return False
    
    def get_idiom_file_path(self, language: str = 'en') -> Optional[str]:
        """
        Get idiom file path (deprecated).
        
        Returns:
            None (local files not used)
        """
        return None
    
    def reload_idiom_file(self, language: str = 'en') -> int:
        """
        Reload idiom file (deprecated).
        
        Returns:
            0 (no file to reload)
        """
        return 0

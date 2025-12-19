"""
Idiom fetcher for phrases and expressions.

Sources:
1. Local idiom text files (idioms_{language}.txt)
2. TheFreeDictionary idioms page (https://idioms.thefreedictionary.com/)

Each language can have its own idiom file with one idiom per line.
Lines starting with # are comments and are ignored.
"""

import re
import requests
from pathlib import Path
from typing import List, Dict, Set, Optional

from ..config import BASE_DIR, API_DELAY
from ..utils.cache import cache_get, cache_set


class IdiomFetcher:
    """
    Fetches idioms and phrases containing target words.
    
    Idiom sources:
    1. Local text files: idioms_{language}.txt or sample_idioms_{language}.txt
    2. TheFreeDictionary idioms website (English only)
    
    File format:
    - One idiom per line
    - Lines starting with # are comments
    - Empty lines are ignored
    """
    
    # TheFreeDictionary idioms base URL
    IDIOMS_URL = "https://idioms.thefreedictionary.com"
    
    def __init__(self):
        # Cache of loaded idiom files: language -> set of idioms
        self._idiom_files: Dict[str, Set[str]] = {}
        self._loaded_languages: Set[str] = set()
    
    def _load_idiom_file(self, language: str) -> Set[str]:
        """
        Load idioms from file for a language.
        
        Searches for:
        1. idioms_{language}.txt
        2. sample_idioms_{language}.txt
        
        Args:
            language: Language code (e.g., 'en', 'de', 'es')
            
        Returns:
            Set of idiom strings (lowercase for matching)
        """
        if language in self._loaded_languages:
            return self._idiom_files.get(language, set())
        
        idioms = set()
        
        # Try both file naming patterns
        filenames = [
            f"idioms_{language}.txt",
            f"sample_idioms_{language}.txt",
        ]
        
        for filename in filenames:
            filepath = BASE_DIR / filename
            if filepath.exists():
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            # Skip empty lines and comments
                            if not line or line.startswith('#'):
                                continue
                            # Store lowercase for matching
                            idioms.add(line.lower())
                    
                    print(f"   ✓ Loaded {len(idioms)} idioms from {filename}")
                except Exception as e:
                    print(f"   ⚠ Error loading {filename}: {e}")
        
        self._idiom_files[language] = idioms
        self._loaded_languages.add(language)
        
        return idioms
    
    def _fetch_from_thefreedictionary(self, word: str) -> List[str]:
        """
        Fetch idioms containing a word from TheFreeDictionary.
        
        Args:
            word: Target word to search for
            
        Returns:
            List of idiom strings
        """
        cache_key = f"idioms_tfd_{word.lower()}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        
        idioms = []
        
        try:
            url = f"{self.IDIOMS_URL}/{word}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; WordbankGenerator/3.1)'
            }
            
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code != 200:
                cache_set(cache_key, [])
                return []
            
            html = resp.text
            
            # Parse idiom entries from the page
            # TheFreeDictionary uses <span class="hw"> for idiom headwords
            # Pattern: <span class="hw">idiom phrase</span>
            hw_pattern = r'<span[^>]*class="[^"]*hw[^"]*"[^>]*>([^<]+)</span>'
            matches = re.findall(hw_pattern, html, re.IGNORECASE)
            
            for match in matches:
                idiom = match.strip()
                # Clean up the idiom
                idiom = re.sub(r'\s+', ' ', idiom)
                if idiom and len(idiom) > 3:
                    # Verify it contains our target word
                    if re.search(rf'\b{re.escape(word)}\b', idiom, re.IGNORECASE):
                        idioms.append(idiom)
            
            # Also try to find idioms in definition lists
            # Pattern: text that looks like an idiom with the word
            # Look for bold or emphasized text patterns
            idiom_patterns = [
                r'<b>([^<]*\b' + re.escape(word) + r'\b[^<]*)</b>',
                r'<strong>([^<]*\b' + re.escape(word) + r'\b[^<]*)</strong>',
            ]
            
            for pattern in idiom_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    idiom = match.strip()
                    idiom = re.sub(r'\s+', ' ', idiom)
                    if idiom and len(idiom) > 3 and idiom not in idioms:
                        # Basic validation: should look like an idiom
                        words = idiom.split()
                        if 2 <= len(words) <= 10:
                            idioms.append(idiom)
            
            # Deduplicate while preserving order
            idioms = list(dict.fromkeys(idioms))
            
        except Exception as e:
            pass
        
        cache_set(cache_key, idioms)
        return idioms
    
    def fetch_idioms(self, word: str, language: str = 'en', 
                     use_web: bool = True) -> List[str]:
        """
        Fetch idioms containing a word from all available sources.
        
        Args:
            word: Target word to search for
            language: Language code (default 'en')
            use_web: Whether to fetch from web sources (default True)
            
        Returns:
            List of idiom strings containing the target word
        """
        word_lower = word.lower().strip()
        idioms = []
        
        # Source 1: Local idiom file
        file_idioms = self._load_idiom_file(language)
        
        # Search for idioms containing the exact word
        word_pattern = re.compile(rf'\b{re.escape(word_lower)}\b')
        for idiom in file_idioms:
            if word_pattern.search(idiom):
                # Return with proper capitalization
                idioms.append(idiom.title() if idiom[0].islower() else idiom)
        
        # Source 2: TheFreeDictionary (English only, if web enabled)
        if use_web and language == 'en':
            web_idioms = self._fetch_from_thefreedictionary(word)
            for idiom in web_idioms:
                if idiom.lower() not in [i.lower() for i in idioms]:
                    idioms.append(idiom)
        
        # Return unique idioms, limited to reasonable count
        return idioms[:10]
    
    def search_idiom_file(self, word: str, language: str = 'en') -> List[str]:
        """
        Search only the local idiom file for phrases containing a word.
        
        This is useful for batch processing or when web access is not wanted.
        
        Args:
            word: Target word to search for
            language: Language code (default 'en')
            
        Returns:
            List of matching idioms from the file
        """
        return self.fetch_idioms(word, language, use_web=False)
    
    def add_idiom_to_file(self, idiom: str, language: str = 'en') -> bool:
        """
        Add a new idiom to the language's idiom file.
        
        Args:
            idiom: Idiom string to add
            language: Language code (default 'en')
            
        Returns:
            True if successfully added
        """
        idiom = idiom.strip()
        if not idiom:
            return False
        
        # Determine filename
        filename = f"idioms_{language}.txt"
        filepath = BASE_DIR / filename
        
        # If file doesn't exist, try to create it
        if not filepath.exists():
            # Check if sample file exists
            sample_path = BASE_DIR / f"sample_idioms_{language}.txt"
            if sample_path.exists():
                # Copy sample to main file first
                try:
                    import shutil
                    shutil.copy(sample_path, filepath)
                except:
                    pass
        
        try:
            # Append to file
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(f"\n{idiom}")
            
            # Update cache
            if language in self._idiom_files:
                self._idiom_files[language].add(idiom.lower())
            
            return True
            
        except Exception as e:
            print(f"Error adding idiom to file: {e}")
            return False
    
    def get_idiom_file_path(self, language: str = 'en') -> Optional[Path]:
        """
        Get the path to the idiom file for a language.
        
        Args:
            language: Language code
            
        Returns:
            Path to the idiom file, or None if not found
        """
        # Check main file first
        main_path = BASE_DIR / f"idioms_{language}.txt"
        if main_path.exists():
            return main_path
        
        # Fall back to sample file
        sample_path = BASE_DIR / f"sample_idioms_{language}.txt"
        if sample_path.exists():
            return sample_path
        
        return None
    
    def reload_idiom_file(self, language: str = 'en') -> int:
        """
        Reload the idiom file for a language.
        
        Useful after external edits to the file.
        
        Args:
            language: Language code
            
        Returns:
            Number of idioms loaded
        """
        # Clear cached data for this language
        if language in self._loaded_languages:
            self._loaded_languages.remove(language)
        if language in self._idiom_files:
            del self._idiom_files[language]
        
        # Reload
        idioms = self._load_idiom_file(language)
        return len(idioms)

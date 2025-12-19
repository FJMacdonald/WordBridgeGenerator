"""
Translation fetcher supporting multiple translation services.

Tries services in order:
1. LibreTranslate (free, self-hostable)
2. MyMemory (free with email)
3. DeepL (API key required)
"""

import time
import requests
from typing import Optional, Dict, List

from ..config import URLS, API_DELAY, DEEPL_API_KEY, MYMEMORY_EMAIL, LIBRETRANSLATE_URL
from ..utils.cache import cache_get, cache_set


class TranslationFetcher:
    """
    Fetches translations from multiple services with fallback.
    """
    
    # Language code mappings
    LANG_CODES = {
        # DeepL codes
        'de': 'DE',
        'es': 'ES', 
        'fr': 'FR',
        'it': 'IT',
        'pt': 'PT',
        'nl': 'NL',
        'pl': 'PL',
        'ru': 'RU',
        'ja': 'JA',
        'zh': 'ZH',
        
        # Standard codes for other services
        'en': 'en',
    }
    
    def __init__(self, libretranslate_url: str = None):
        """
        Initialize translation fetcher.
        
        Args:
            libretranslate_url: Custom LibreTranslate instance URL
                               Default is from LIBRETRANSLATE_URL env var
                               or http://localhost:5001/translate
        """
        self.libretranslate_url = libretranslate_url or LIBRETRANSLATE_URL
        self._libretranslate_available = None
    
    def translate(self, text: str, source_lang: str = 'en', 
                  target_lang: str = 'de') -> Optional[str]:
        """
        Translate text using available services.
        
        Tries in order: LibreTranslate -> MyMemory -> DeepL
        
        Args:
            text: Text to translate
            source_lang: Source language code
            target_lang: Target language code
            
        Returns:
            Translated text or None if all services fail
        """
        if not text or not text.strip():
            return None
        
        text = text.strip()
        
        # Check cache
        cache_key = f"translation_{source_lang}_{target_lang}_{hash(text)}"
        cached = cache_get(cache_key)
        if cached:
            return cached
        
        result = None
        
        # Try LibreTranslate first
        result = self._translate_libretranslate(text, source_lang, target_lang)
        
        # Try MyMemory if LibreTranslate fails
        if not result:
            time.sleep(API_DELAY)
            result = self._translate_mymemory(text, source_lang, target_lang)
        
        # Try DeepL if others fail
        if not result and DEEPL_API_KEY:
            time.sleep(API_DELAY)
            result = self._translate_deepl(text, source_lang, target_lang)
        
        # Cache successful translation
        if result:
            cache_set(cache_key, result)
        
        return result
    
    def translate_batch(self, texts: List[str], source_lang: str = 'en',
                        target_lang: str = 'de') -> List[Optional[str]]:
        """
        Translate multiple texts.
        
        Args:
            texts: List of texts to translate
            source_lang: Source language code
            target_lang: Target language code
            
        Returns:
            List of translations (None for failed translations)
        """
        results = []
        for text in texts:
            result = self.translate(text, source_lang, target_lang)
            results.append(result)
            time.sleep(API_DELAY)
        return results
    
    def _translate_libretranslate(self, text: str, source: str, 
                                   target: str) -> Optional[str]:
        """Translate using LibreTranslate."""
        if self._libretranslate_available is False:
            return None
        
        try:
            resp = requests.post(
                self.libretranslate_url,
                json={
                    'q': text,
                    'source': source,
                    'target': target,
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self._libretranslate_available = True
                return data.get('translatedText')
            else:
                self._libretranslate_available = False
                return None
                
        except Exception as e:
            self._libretranslate_available = False
            return None
    
    def _translate_mymemory(self, text: str, source: str, 
                            target: str) -> Optional[str]:
        """Translate using MyMemory API."""
        try:
            params = {
                'q': text,
                'langpair': f'{source}|{target}',
            }
            
            # Add email for higher rate limit
            if MYMEMORY_EMAIL:
                params['de'] = MYMEMORY_EMAIL
            
            resp = requests.get(URLS['mymemory'], params=params, timeout=10)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            
            if data.get('responseStatus') == 200:
                return data.get('responseData', {}).get('translatedText')
            
            return None
            
        except Exception as e:
            return None
    
    def _translate_deepl(self, text: str, source: str, 
                         target: str) -> Optional[str]:
        """Translate using DeepL API."""
        if not DEEPL_API_KEY:
            return None
        
        try:
            # Convert language codes to DeepL format
            source_code = self.LANG_CODES.get(source, source.upper())
            target_code = self.LANG_CODES.get(target, target.upper())
            
            resp = requests.post(
                URLS['deepl'],
                headers={
                    'Authorization': f'DeepL-Auth-Key {DEEPL_API_KEY}',
                },
                data={
                    'text': text,
                    'source_lang': source_code,
                    'target_lang': target_code,
                },
                timeout=10
            )
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            translations = data.get('translations', [])
            
            if translations:
                return translations[0].get('text')
            
            return None
            
        except Exception as e:
            return None
    
    def check_services(self) -> Dict[str, bool]:
        """
        Check availability of translation services.
        
        Returns:
            Dict mapping service name to availability
        """
        status = {
            'libretranslate': False,
            'mymemory': False,
            'deepl': False,
        }
        
        # Test LibreTranslate
        try:
            result = self._translate_libretranslate('test', 'en', 'de')
            status['libretranslate'] = result is not None
        except:
            pass
        
        # Test MyMemory
        try:
            result = self._translate_mymemory('test', 'en', 'de')
            status['mymemory'] = result is not None
        except:
            pass
        
        # Check DeepL (just check if API key is set)
        status['deepl'] = bool(DEEPL_API_KEY)
        
        return status

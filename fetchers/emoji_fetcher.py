"""
Emoji and image fetcher with fallback strategy.

Fallback strategy for finding suitable emoji/image:
1. Search BehrouzSohrabi/Emoji database
2. Search OpenMoji database  
3. Use The Noun Project API (with attribution)
4. Leave blank if all three fail

Key features:
- Uses text field to find most generic emoji when multiple match
- OpenMoji fallback for additional emoji coverage
- Noun Project integration with proper attribution
- Rate limit handling for Noun Project API
"""

import re
import time
import requests
import base64
import hashlib
import hmac
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict
from datetime import datetime
from urllib.parse import quote

from ..config import (
    URLS, API_DELAY, EXCLUDED_WORDS, 
    NOUN_PROJECT_KEY, NOUN_PROJECT_SECRET, RATE_LIMITS
)
from ..utils.cache import cache_get, cache_set


# Number word to digit mapping for keycap matching
NUMBER_WORDS = {
    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
    'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
    'ten': '10',
}


class EmojiFetcher:
    """
    Fetches emoji/image data with fallback strategy:
    1. BehrouzSohrabi/Emoji database
    2. OpenMoji database
    3. The Noun Project API (with attribution required)
    4. Leave blank if all fail
    
    Attributes:
        requires_attribution: Set of words that use Noun Project images
        missing_images: Set of words that need manual image input
    """
    
    # OpenMoji data URL
    OPENMOJI_URL = "https://raw.githubusercontent.com/hfg-gmuend/openmoji/master/data/openmoji.json"
    
    def __init__(self):
        # emoji char -> metadata (includes source)
        self.emoji_metadata: Dict[str, Dict] = {}
        
        # OpenMoji specific data
        self.openmoji_metadata: Dict[str, Dict] = {}
        
        # keyword -> list of (emoji, metadata, source) tuples
        self.keyword_index: Dict[str, List[Tuple[str, Dict, str]]] = defaultdict(list)
        
        # Words using Noun Project (need attribution)
        self.requires_attribution: Dict[str, Dict] = {}
        
        # Words with no image found
        self.missing_images: Set[str] = set()
        
        self._fetched = False
        
        # Noun Project rate limiting
        self._np_requests_this_minute = 0
        self._np_minute_start = time.time()
        self._np_available = True
    
    def fetch(self) -> bool:
        """Fetch emoji data from BehrouzSohrabi/Emoji and OpenMoji sources."""
        if self._fetched:
            return True
        
        # Try cache first
        cached = cache_get("emoji_categories_v6")
        if cached:
            self.emoji_metadata = cached.get('metadata', {})
            self.openmoji_metadata = cached.get('openmoji', {})
            self._build_keyword_index()
            self._fetched = True
            return True
        
        # Fetch BehrouzSohrabi/Emoji
        print("😀 Fetching emoji data from BehrouzSohrabi/Emoji...")
        
        try:
            resp = requests.get(URLS['emoji_categories'], timeout=30)
            resp.raise_for_status()
            emoji_data = resp.json()
            
            if isinstance(emoji_data, dict):
                for category, emoji_list in emoji_data.items():
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
                        
                        self.emoji_metadata[emoji_char] = {
                            'text': text,
                            'keywords': keywords,
                            'category': category,
                            'source': 'BehrouzSohrabi',
                        }
                
                print(f"   ✓ Loaded {len(self.emoji_metadata)} emoji entries from BehrouzSohrabi")
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch BehrouzSohrabi emoji data: {e}")
        
        time.sleep(API_DELAY)
        
        # Fetch OpenMoji
        print("😀 Fetching emoji data from OpenMoji...")
        
        try:
            resp = requests.get(self.OPENMOJI_URL, timeout=30)
            resp.raise_for_status()
            openmoji_data = resp.json()
            
            for item in openmoji_data:
                if not isinstance(item, dict):
                    continue
                
                hexcode = item.get('hexcode', '')
                if not hexcode:
                    continue
                
                try:
                    emoji_char = ''.join(chr(int(code, 16)) for code in hexcode.split('-'))
                except (ValueError, OverflowError):
                    continue
                
                # Skip if already in BehrouzSohrabi
                if emoji_char in self.emoji_metadata:
                    continue
                
                annotation = item.get('annotation', '').lower()
                tags = item.get('tags', '').lower().split(',') if item.get('tags') else []
                tags = [t.strip() for t in tags if t.strip()]
                group = item.get('group', '')
                
                self.openmoji_metadata[emoji_char] = {
                    'text': annotation,
                    'keywords': tags + ([annotation] if annotation else []),
                    'category': group,
                    'source': 'OpenMoji',
                }
            
            print(f"   ✓ Loaded {len(self.openmoji_metadata)} additional emoji entries from OpenMoji")
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch OpenMoji data: {e}")
        
        # If no emoji data at all, try legacy fallback
        if len(self.emoji_metadata) == 0 and len(self.openmoji_metadata) == 0:
            return self._fetch_fallback()
        
        self._build_keyword_index()
        
        cache_set("emoji_categories_v6", {
            'metadata': self.emoji_metadata,
            'openmoji': self.openmoji_metadata,
        })
        
        self._fetched = True
        return True
    
    def _fetch_fallback(self) -> bool:
        """Fallback to original emoji sources."""
        try:
            resp = requests.get(URLS['emoji_data'], timeout=30)
            resp.raise_for_status()
            emoji_data_list = resp.json()
            
            emoji_categories = {}
            for item in emoji_data_list:
                unified = item.get('unified', '')
                try:
                    emoji_char = ''.join(
                        chr(int(code, 16)) for code in unified.split('-')
                    )
                except (ValueError, OverflowError):
                    continue
                
                emoji_categories[emoji_char] = {
                    'name': item.get('name', ''),
                    'short_name': item.get('short_name', ''),
                    'category': item.get('category', ''),
                }
            
            time.sleep(API_DELAY)
            
            resp = requests.get(URLS['emojilib'], timeout=30)
            resp.raise_for_status()
            emojilib_data = resp.json()
            
            for emoji_char, keywords in emojilib_data.items():
                if isinstance(keywords, list) and keywords:
                    meta = emoji_categories.get(emoji_char, {})
                    text = keywords[0].replace('_', ' ').replace('-', ' ') if keywords else ''
                    
                    self.emoji_metadata[emoji_char] = {
                        'text': text.lower(),
                        'keywords': [k.lower().replace('_', ' ').replace('-', ' ') for k in keywords],
                        'category': meta.get('category', ''),
                    }
            
            print(f"   ✓ Loaded {len(self.emoji_metadata)} emoji entries (fallback)")
            
            self._build_keyword_index()
            
            cache_set("emoji_categories_v5", {
                'metadata': self.emoji_metadata,
            })
            
            self._fetched = True
            return True
            
        except Exception as e:
            print(f"   ⚠ Fallback also failed: {e}")
            return False
    
    def _build_keyword_index(self):
        """Build reverse index from keywords to emojis.
        
        Index includes source information for fallback prioritization:
        BehrouzSohrabi -> OpenMoji -> Noun Project
        """
        self.keyword_index = defaultdict(list)
        
        # Index BehrouzSohrabi first (higher priority)
        for emoji_char, metadata in self.emoji_metadata.items():
            keywords = metadata.get('keywords', [])
            source = metadata.get('source', 'BehrouzSohrabi')
            
            for keyword in keywords:
                keyword_lower = keyword.lower().strip()
                if keyword_lower:
                    self.keyword_index[keyword_lower].append((emoji_char, metadata, source))
        
        # Index OpenMoji (lower priority)
        for emoji_char, metadata in self.openmoji_metadata.items():
            keywords = metadata.get('keywords', [])
            source = metadata.get('source', 'OpenMoji')
            
            for keyword in keywords:
                keyword_lower = keyword.lower().strip()
                if keyword_lower:
                    self.keyword_index[keyword_lower].append((emoji_char, metadata, source))
    
    def _find_most_generic_emoji(self, candidates: List[Tuple[str, Dict, str]], 
                                  target_word: str) -> Tuple[str, Dict, str]:
        """Find the most generic emoji from candidates based on text field.
        
        Candidates are tuples of (emoji_char, metadata, source).
        Prioritizes BehrouzSohrabi over OpenMoji.
        """
        if not candidates:
            return '', {}, ''
        
        if len(candidates) == 1:
            return candidates[0]
        
        scored = []
        target_lower = target_word.lower()
        
        for emoji, metadata, source in candidates:
            text = metadata.get('text', '').lower()
            keywords = metadata.get('keywords', [])
            
            score = 0
            
            # Prefer BehrouzSohrabi over OpenMoji
            if source == 'BehrouzSohrabi':
                score += 50
            
            if text == target_lower:
                score += 1000
            elif target_lower in text.split():
                score += 500
            
            word_count = len(text.split())
            if word_count == 1:
                score += 200
            elif word_count == 2:
                score += 100
            else:
                score += 50 / word_count
            
            if keywords and keywords[0].lower() == target_lower:
                score += 150
            
            if text.startswith('no ') and target_lower != 'no':
                score -= 100
            
            scored.append((score, emoji, metadata, source))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        return scored[0][1], scored[0][2], scored[0][3]
    
    def _find_number_keycap(self, word: str) -> Tuple[str, str]:
        """Find keycap emoji for number words."""
        word_lower = word.lower()
        
        if word_lower not in NUMBER_WORDS:
            return '', ''
        
        digit = NUMBER_WORDS[word_lower]
        
        for emoji, metadata in self.emoji_metadata.items():
            text = metadata.get('text', '').lower()
            keywords = metadata.get('keywords', [])
            
            if 'keycap' in text:
                if digit in keywords or digit in text:
                    return (emoji, metadata.get('category', ''))
        
        return '', ''
    
    def _check_noun_project_rate_limit(self) -> bool:
        """Check if we can make a Noun Project request."""
        now = time.time()
        
        if now - self._np_minute_start > 60:
            self._np_requests_this_minute = 0
            self._np_minute_start = now
        
        limit = RATE_LIMITS['noun_project']['requests_per_minute']
        return self._np_requests_this_minute < limit
    
    def _fetch_from_noun_project(self, word: str) -> Optional[Dict]:
        """
        Fetch icon from The Noun Project API.
        
        Uses OAuth 1.0a authentication. Key requirements per Noun Project docs:
        - Nonce must be at least 8 characters and unique per request
        - Timestamp must be accurate to current time
        - Signature base string must include ALL parameters (OAuth + query params)
        
        Returns dict with:
            - icon_url: URL to the icon
            - attribution: Required attribution text
            - attribution_preview_url: Preview URL for attribution
            
        Note: Icons from Noun Project require attribution.
        """
        if not NOUN_PROJECT_KEY or not NOUN_PROJECT_SECRET:
            return None
        
        if not self._check_noun_project_rate_limit():
            return None
        
        try:
            import uuid
            from urllib.parse import urlencode
            
            base_url = URLS['noun_project']
            
            # Query parameters
            query_params = {
                'query': word,
                'limit': '1',
            }
            
            # OAuth 1.0a parameters
            # Nonce must be at least 8 characters and unique per request
            timestamp = str(int(time.time()))
            nonce = uuid.uuid4().hex  # Guaranteed unique, 32 chars
            
            oauth_params = {
                'oauth_consumer_key': NOUN_PROJECT_KEY,
                'oauth_nonce': nonce,
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': timestamp,
                'oauth_version': '1.0',
            }
            
            # Combine ALL parameters for signature base string (OAuth + query params)
            all_params = {**oauth_params, **query_params}
            
            # Sort and encode parameters for signature base string
            sorted_params = sorted(all_params.items())
            param_string = '&'.join(
                f'{quote(str(k), safe="")}={quote(str(v), safe="")}' 
                for k, v in sorted_params
            )
            
            # Create signature base string: METHOD&URL&PARAMS
            base_string = f"GET&{quote(base_url, safe='')}&{quote(param_string, safe='')}"
            
            # Sign with HMAC-SHA1 (key is consumer_secret + '&' + token_secret, but no token for 2-legged OAuth)
            signing_key = f"{NOUN_PROJECT_SECRET}&"
            signature = base64.b64encode(
                hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
            ).decode()
            
            oauth_params['oauth_signature'] = signature
            
            # Build Authorization header
            auth_header = 'OAuth ' + ', '.join(
                f'{quote(str(k), safe="")}="{quote(str(v), safe="")}"' 
                for k, v in sorted(oauth_params.items())
            )
            
            headers = {'Authorization': auth_header}
            
            # Build full URL with query params
            full_url = f"{base_url}?{urlencode(query_params)}"
            
            resp = requests.get(full_url, headers=headers, timeout=10)
            
            self._np_requests_this_minute += 1
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            icons = data.get('icons', [])
            
            if not icons:
                return None
            
            icon = icons[0]
            
            return {
                'icon_url': icon.get('icon_url') or icon.get('preview_url'),
                'attribution': icon.get('attribution', 'Icon from The Noun Project'),
                'attribution_preview_url': icon.get('attribution_preview_url', ''),
                'term': icon.get('term', word),
                'id': icon.get('id'),
            }
            
        except Exception as e:
            return None
    
    def find_best_emoji(self, word: str, definition: str = "", 
                        synonyms: List[str] = None,
                        pos: str = "") -> Tuple[str, str, Optional[Dict]]:
        """
        Find the best emoji/image for a word.
        
        Fallback strategy:
        1. Search BehrouzSohrabi/Emoji database
        2. Search OpenMoji database
        3. Use The Noun Project API
        4. Leave blank if all fail
        
        Returns:
            Tuple of (emoji_or_empty, category, noun_project_info_or_none)
            
        If noun_project_info is not None, the image requires attribution.
        If both emoji and noun_project_info are empty, the word has no image.
        """
        if not self._fetched:
            self.fetch()
        
        word_lower = word.lower().strip()
        synonyms = synonyms or []
        
        # Strategy 1: Handle number words specially
        if word_lower in NUMBER_WORDS:
            result = self._find_number_keycap(word_lower)
            if result[0]:
                return (result[0], result[1], None)
        
        # Strategy 2: Direct keyword match in emoji database (BehrouzSohrabi + OpenMoji)
        if word_lower in self.keyword_index:
            candidates = self.keyword_index[word_lower]
            
            # Filter out flags unless searching for flag
            non_flag_candidates = [
                (e, m, s) for e, m, s in candidates 
                if m.get('category', '').lower() != 'flags'
            ]
            
            if non_flag_candidates:
                emoji, metadata, source = self._find_most_generic_emoji(non_flag_candidates, word_lower)
            elif candidates:
                emoji, metadata, source = self._find_most_generic_emoji(candidates, word_lower)
            else:
                emoji, metadata, source = '', {}, ''
            
            if emoji:
                category = metadata.get('category', '') if pos == 'noun' else ''
                return (emoji, category, None)
        
        # Strategy 3: Try word variations
        variations = self._get_word_variations(word_lower)
        for var in variations:
            if var in self.keyword_index and var != word_lower:
                candidates = self.keyword_index[var]
                non_flag = [(e, m, s) for e, m, s in candidates if m.get('category', '').lower() != 'flags']
                
                if non_flag:
                    emoji, metadata, source = self._find_most_generic_emoji(non_flag, var)
                    if emoji:
                        category = metadata.get('category', '') if pos == 'noun' else ''
                        return (emoji, category, None)
        
        # Strategy 4: Synonym matching
        for syn in synonyms[:5]:
            syn_lower = syn.lower()
            if syn_lower in self.keyword_index:
                candidates = self.keyword_index[syn_lower]
                non_flag = [(e, m, s) for e, m, s in candidates if m.get('category', '').lower() != 'flags']
                
                if non_flag:
                    emoji, metadata, source = self._find_most_generic_emoji(non_flag, syn_lower)
                    if emoji:
                        category = metadata.get('category', '') if pos == 'noun' else ''
                        return (emoji, category, None)
        
        # Strategy 5: Try The Noun Project API
        noun_project_result = self._fetch_from_noun_project(word)
        if noun_project_result:
            # Record that this word uses Noun Project (needs attribution)
            self.requires_attribution[word_lower] = noun_project_result
            return ('', '', noun_project_result)
        
        # Strategy 6: Leave blank - no manual input flagging
        self.missing_images.add(word_lower)
        return ('', '', None)
    
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
            variations.append(word + 'es')
        
        if word.endswith('ing'):
            base = word[:-3]
            variations.append(base)
            variations.append(base + 'e')
        elif word.endswith('ed'):
            base = word[:-2]
            variations.append(base)
            variations.append(base + 'e')
        else:
            variations.append(word + 'ing')
            variations.append(word + 'ed')
        
        if word.endswith('ly'):
            variations.append(word[:-2])
        if word.endswith('er'):
            variations.append(word[:-2])
        if word.endswith('est'):
            variations.append(word[:-3])
        
        return [v for v in variations if len(v) >= 2]
    
    def get_category_for_emoji(self, emoji: str) -> str:
        """Get category for an emoji."""
        if not self._fetched:
            self.fetch()
        
        meta = self.emoji_metadata.get(emoji, {})
        return meta.get('category', '')
    
    def get_words_needing_manual_input(self) -> Set[str]:
        """Get words that need manual image input."""
        return self.missing_images.copy()
    
    def get_words_with_attribution(self) -> Dict[str, Dict]:
        """Get words that use Noun Project images (need attribution)."""
        return self.requires_attribution.copy()
    
    def search(self, query: str, limit: int = 30) -> List[Dict]:
        """Search for emojis matching a query."""
        if not self._fetched:
            self.fetch()
        
        query_lower = query.lower().strip()
        if not query_lower:
            return []
        
        results = []
        seen = set()
        
        if query_lower in self.keyword_index:
            for emoji, meta, source in self.keyword_index[query_lower]:
                if emoji not in seen:
                    results.append(self._make_result(emoji, meta))
                    seen.add(emoji)
        
        for keyword in self.keyword_index:
            if query_lower in keyword and keyword != query_lower:
                for emoji, meta, source in self.keyword_index[keyword][:2]:
                    if emoji not in seen:
                        results.append(self._make_result(emoji, meta))
                        seen.add(emoji)
        
        # Search BehrouzSohrabi metadata
        for emoji, meta in self.emoji_metadata.items():
            if emoji in seen:
                continue
            text = meta.get('text', '').lower()
            if query_lower in text:
                results.append(self._make_result(emoji, meta))
                seen.add(emoji)
        
        # Search OpenMoji metadata
        for emoji, meta in self.openmoji_metadata.items():
            if emoji in seen:
                continue
            text = meta.get('text', '').lower()
            if query_lower in text:
                results.append(self._make_result(emoji, meta))
                seen.add(emoji)
        
        return results[:limit]
    
    def _make_result(self, emoji: str, meta: Dict) -> Dict:
        """Create a search result dict."""
        return {
            'emoji': emoji,
            'name': meta.get('text', ''),
            'keywords': meta.get('keywords', [])[:5],
            'category': meta.get('category', ''),
        }
    
    def get_all_categories(self) -> List[str]:
        """Get all unique categories from both BehrouzSohrabi and OpenMoji."""
        if not self._fetched:
            self.fetch()
        
        categories = set()
        for meta in self.emoji_metadata.values():
            cat = meta.get('category', '')
            if cat:
                categories.add(cat)
        for meta in self.openmoji_metadata.values():
            cat = meta.get('category', '')
            if cat:
                categories.add(cat)
        
        return sorted(categories)
    
    def get_emojis_by_category(self, category: str) -> List[Dict]:
        """Get all emojis in a category from both sources."""
        if not self._fetched:
            self.fetch()
        
        results = []
        for emoji, meta in self.emoji_metadata.items():
            if meta.get('category', '').lower() == category.lower():
                results.append(self._make_result(emoji, meta))
        for emoji, meta in self.openmoji_metadata.items():
            if meta.get('category', '').lower() == category.lower():
                results.append(self._make_result(emoji, meta))
        
        return results

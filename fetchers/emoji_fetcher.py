"""
Emoji and image fetcher with fallback strategy.

Fallback strategy for finding suitable emoji/image:
1. Search BehrouzSohrabi/Emoji database
2. Use The Noun Project API (with attribution)
3. Flag for manual input if no image found

Key features:
- Uses text field to find most generic emoji when multiple match
- Noun Project integration with proper attribution
- Rate limit handling for Noun Project API
- Manual review flagging when no image found
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
    2. The Noun Project API (with attribution required)
    3. Flag for manual input
    
    Attributes:
        requires_attribution: Set of words that use Noun Project images
        missing_images: Set of words that need manual image input
    """
    
    def __init__(self):
        # emoji char -> metadata
        self.emoji_metadata: Dict[str, Dict] = {}
        
        # keyword -> list of (emoji, metadata) tuples
        self.keyword_index: Dict[str, List[Tuple[str, Dict]]] = defaultdict(list)
        
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
        """Fetch emoji data from BehrouzSohrabi/Emoji source."""
        if self._fetched:
            return True
        
        # Try cache first
        cached = cache_get("emoji_categories_v5")
        if cached:
            self.emoji_metadata = cached.get('metadata', {})
            self._build_keyword_index()
            self._fetched = True
            return True
        
        print("😀 Fetching emoji data from BehrouzSohrabi/Emoji...")
        
        try:
            resp = requests.get(URLS['emoji_categories'], timeout=30)
            resp.raise_for_status()
            emoji_data = resp.json()
            
            if not isinstance(emoji_data, dict):
                print(f"   ⚠ Unexpected data format: {type(emoji_data)}")
                return self._fetch_fallback()
            
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
                    }
            
            if len(self.emoji_metadata) == 0:
                return self._fetch_fallback()
            
            print(f"   ✓ Loaded {len(self.emoji_metadata)} emoji entries")
            
            self._build_keyword_index()
            
            cache_set("emoji_categories_v5", {
                'metadata': self.emoji_metadata,
            })
            
            self._fetched = True
            return True
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch emoji data: {e}")
            return self._fetch_fallback()
    
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
        """Build reverse index from keywords to emojis."""
        self.keyword_index = defaultdict(list)
        
        for emoji_char, metadata in self.emoji_metadata.items():
            keywords = metadata.get('keywords', [])
            
            for keyword in keywords:
                keyword_lower = keyword.lower().strip()
                if keyword_lower:
                    self.keyword_index[keyword_lower].append((emoji_char, metadata))
    
    def _find_most_generic_emoji(self, candidates: List[Tuple[str, Dict]], 
                                  target_word: str) -> Tuple[str, Dict]:
        """Find the most generic emoji from candidates based on text field."""
        if not candidates:
            return '', {}
        
        if len(candidates) == 1:
            return candidates[0]
        
        scored = []
        target_lower = target_word.lower()
        
        for emoji, metadata in candidates:
            text = metadata.get('text', '').lower()
            keywords = metadata.get('keywords', [])
            
            score = 0
            
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
            
            scored.append((score, emoji, metadata))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        return scored[0][1], scored[0][2]
    
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
            # OAuth 1.0 authentication for Noun Project
            url = f"{URLS['noun_project']}?query={quote(word)}&limit=1"
            
            # Simple OAuth signature (HMAC-SHA1)
            timestamp = str(int(time.time()))
            nonce = hashlib.md5(f"{timestamp}{word}".encode()).hexdigest()
            
            oauth_params = {
                'oauth_consumer_key': NOUN_PROJECT_KEY,
                'oauth_nonce': nonce,
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': timestamp,
                'oauth_version': '1.0',
            }
            
            # Build signature base string
            base_params = '&'.join(f'{k}={quote(str(v), safe="")}' 
                                   for k, v in sorted(oauth_params.items()))
            base_string = f"GET&{quote(URLS['noun_project'], safe='')}&{quote(base_params, safe='')}"
            
            # Sign with HMAC-SHA1
            signing_key = f"{NOUN_PROJECT_SECRET}&"
            signature = base64.b64encode(
                hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
            ).decode()
            
            oauth_params['oauth_signature'] = signature
            
            # Build Authorization header
            auth_header = 'OAuth ' + ', '.join(
                f'{k}="{quote(str(v), safe="")}"' 
                for k, v in sorted(oauth_params.items())
            )
            
            headers = {'Authorization': auth_header}
            
            resp = requests.get(
                f"{URLS['noun_project']}?query={quote(word)}&limit=1",
                headers=headers,
                timeout=10
            )
            
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
        2. Use The Noun Project API
        3. Flag for manual input
        
        Returns:
            Tuple of (emoji_or_empty, category, noun_project_info_or_none)
            
        If noun_project_info is not None, the image requires attribution.
        If both emoji and noun_project_info are empty, the word needs manual input.
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
        
        # Strategy 2: Direct keyword match in emoji database
        if word_lower in self.keyword_index:
            candidates = self.keyword_index[word_lower]
            
            non_flag_candidates = [
                (e, m) for e, m in candidates 
                if m.get('category', '') != 'Flags'
            ]
            
            if non_flag_candidates:
                emoji, metadata = self._find_most_generic_emoji(non_flag_candidates, word_lower)
            elif candidates:
                emoji, metadata = self._find_most_generic_emoji(candidates, word_lower)
            else:
                emoji, metadata = '', {}
            
            if emoji:
                category = metadata.get('category', '') if pos == 'noun' else ''
                return (emoji, category, None)
        
        # Strategy 3: Try word variations
        variations = self._get_word_variations(word_lower)
        for var in variations:
            if var in self.keyword_index and var != word_lower:
                candidates = self.keyword_index[var]
                non_flag = [(e, m) for e, m in candidates if m.get('category', '') != 'Flags']
                
                if non_flag:
                    emoji, metadata = self._find_most_generic_emoji(non_flag, var)
                    if emoji:
                        category = metadata.get('category', '') if pos == 'noun' else ''
                        return (emoji, category, None)
        
        # Strategy 4: Synonym matching
        for syn in synonyms[:5]:
            syn_lower = syn.lower()
            if syn_lower in self.keyword_index:
                candidates = self.keyword_index[syn_lower]
                non_flag = [(e, m) for e, m in candidates if m.get('category', '') != 'Flags']
                
                if non_flag:
                    emoji, metadata = self._find_most_generic_emoji(non_flag, syn_lower)
                    if emoji:
                        category = metadata.get('category', '') if pos == 'noun' else ''
                        return (emoji, category, None)
        
        # Strategy 5: Try The Noun Project API
        noun_project_result = self._fetch_from_noun_project(word)
        if noun_project_result:
            # Record that this word uses Noun Project (needs attribution)
            self.requires_attribution[word_lower] = noun_project_result
            return ('', '', noun_project_result)
        
        # Strategy 6: Flag for manual input
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
            for emoji, meta in self.keyword_index[query_lower]:
                if emoji not in seen:
                    results.append(self._make_result(emoji, meta))
                    seen.add(emoji)
        
        for keyword in self.keyword_index:
            if query_lower in keyword and keyword != query_lower:
                for emoji, meta in self.keyword_index[keyword][:2]:
                    if emoji not in seen:
                        results.append(self._make_result(emoji, meta))
                        seen.add(emoji)
        
        for emoji, meta in self.emoji_metadata.items():
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
        """Get all unique categories."""
        if not self._fetched:
            self.fetch()
        
        categories = set()
        for meta in self.emoji_metadata.values():
            cat = meta.get('category', '')
            if cat:
                categories.add(cat)
        
        return sorted(categories)
    
    def get_emojis_by_category(self, category: str) -> List[Dict]:
        """Get all emojis in a category."""
        if not self._fetched:
            self.fetch()
        
        results = []
        for emoji, meta in self.emoji_metadata.items():
            if meta.get('category', '').lower() == category.lower():
                results.append(self._make_result(emoji, meta))
        
        return results

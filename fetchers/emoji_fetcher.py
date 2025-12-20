"""
Emoji data fetcher with intelligent matching algorithm.

Fetches from:
- BehrouzSohrabi/Emoji for categories, text descriptions, and keywords

The matching algorithm uses the `text` field to find the most generic emoji:
1. When multiple emojis share a keyword, use the `text` field to pick the most generic
2. For example, "not" matches "prohibited" (🚫) instead of "no smoking" (🚭)
3. For numbers like "one", look for keycap emojis

Key improvements:
- Uses `text` field to find most generic/abstract emoji when keyword matches multiple
- Special handling for number words to find keycap emojis
- No fallbacks - returns empty if no good match found
"""

import re
import time
import requests
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict

from ..config import URLS, API_DELAY, EXCLUDED_WORDS
from ..utils.cache import cache_get, cache_set


# Number word to digit mapping for keycap matching
NUMBER_WORDS = {
    'zero': '0',
    'one': '1',
    'two': '2',
    'three': '3',
    'four': '4',
    'five': '5',
    'six': '6',
    'seven': '7',
    'eight': '8',
    'nine': '9',
    'ten': '10',
}


class EmojiFetcher:
    """
    Fetches and matches emoji data from BehrouzSohrabi/Emoji source.
    
    This source includes:
    - emoji: The emoji character
    - text: Human-readable description (used for finding most generic match)
    - keywords: List of keywords for matching
    - category/subcategory: For categorization
    
    No fallback emojis - if no match is found, returns empty string.
    """
    
    def __init__(self):
        # emoji char -> metadata (category, subcategory, text, keywords)
        self.emoji_metadata: Dict[str, Dict] = {}
        
        # Reverse index: keyword -> list of (emoji, metadata) tuples
        self.keyword_index: Dict[str, List[Tuple[str, Dict]]] = defaultdict(list)
        
        # Category mapping for nouns (text description -> category)
        self.category_from_text: Dict[str, str] = {}
        
        self._fetched = False
    
    def fetch(self) -> bool:
        """Fetch emoji data from BehrouzSohrabi/Emoji source."""
        if self._fetched:
            return True
        
        # Try cache first
        cached = cache_get("emoji_categories_v4")
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
            
            # BehrouzSohrabi format: {"Category Name": [emoji_objects...], ...}
            if not isinstance(emoji_data, dict):
                print(f"   ⚠ Unexpected data format: {type(emoji_data)}")
                return self._fetch_fallback()
            
            for category, emoji_list in emoji_data.items():
                # Skip if not a list of emojis
                if not isinstance(emoji_list, list):
                    continue
                
                for item in emoji_list:
                    # Skip if item is not a dict
                    if not isinstance(item, dict):
                        continue
                    
                    emoji_char = item.get('emoji', '')
                    if not emoji_char:
                        continue
                    
                    text = item.get('text', '').lower() if item.get('text') else ''
                    
                    # Handle keywords - should be a list in this format
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
                        'category': category,  # Category comes from the dict key
                    }
                    
                    # Map text to category for noun categorization
                    if text and category:
                        self.category_from_text[text] = category
            
            if len(self.emoji_metadata) == 0:
                print(f"   ⚠ No emoji entries loaded from primary source")
                return self._fetch_fallback()
            
            print(f"   ✓ Loaded {len(self.emoji_metadata)} emoji entries")
            
            # Build index and cache
            self._build_keyword_index()
            
            cache_set("emoji_categories_v4", {
                'metadata': self.emoji_metadata,
            })
            
            self._fetched = True
            return True
            
        except Exception as e:
            import traceback
            print(f"   ⚠ Failed to fetch emoji data: {e}")
            print(f"   Traceback: {traceback.format_exc()}")
            print("   Trying fallback sources (emojilib + emoji-data)...")
            return self._fetch_fallback()
    
    def _fetch_fallback(self) -> bool:
        """Fallback to original emoji sources if primary fails."""
        try:
            # Fetch emoji-data for categories
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
            
            print(f"   ✓ Loaded {len(emoji_categories)} emoji metadata entries (fallback)")
            
            time.sleep(API_DELAY)
            
            # Fetch emojilib for keywords
            resp = requests.get(URLS['emojilib'], timeout=30)
            resp.raise_for_status()
            emojilib_data = resp.json()
            
            for emoji_char, keywords in emojilib_data.items():
                if isinstance(keywords, list) and keywords:
                    meta = emoji_categories.get(emoji_char, {})
                    # Use first keyword as "text" for consistency
                    text = keywords[0].replace('_', ' ').replace('-', ' ') if keywords else ''
                    
                    self.emoji_metadata[emoji_char] = {
                        'text': text.lower(),
                        'keywords': [k.lower().replace('_', ' ').replace('-', ' ') for k in keywords],
                        'category': meta.get('category', ''),
                    }
            
            print(f"   ✓ Loaded {len(self.emoji_metadata)} emoji keyword entries (fallback)")
            
            self._build_keyword_index()
            
            cache_set("emoji_categories_v4", {
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
        """
        Find the most generic emoji from candidates based on text field.
        
        Strategy:
        1. Prefer emojis where text is shortest (more abstract/generic)
        2. Prefer emojis where text equals or contains only the target word
        3. Deprioritize emojis with compound descriptions (e.g., "no smoking" vs "prohibited")
        
        Args:
            candidates: List of (emoji, metadata) tuples
            target_word: The word we're matching
            
        Returns:
            Best (emoji, metadata) tuple
        """
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
            
            # Exact text match with target word is best
            if text == target_lower:
                score += 1000
            
            # Text is the target word (like "prohibited" for "prohibited")
            elif target_lower in text.split():
                score += 500
            
            # Shorter text descriptions are more generic
            # "prohibited" is better than "no smoking"
            word_count = len(text.split())
            if word_count == 1:
                score += 200
            elif word_count == 2:
                score += 100
            else:
                score += 50 / word_count  # Penalize longer descriptions
            
            # Bonus if target is the first keyword
            if keywords and keywords[0].lower() == target_lower:
                score += 150
            
            # Penalty for compound descriptions starting with "no"
            # These are specific prohibitions rather than generic concepts
            if text.startswith('no ') and target_lower != 'no':
                score -= 100
            
            scored.append((score, emoji, metadata))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        
        return scored[0][1], scored[0][2]
    
    def _find_number_keycap(self, word: str) -> Tuple[str, str]:
        """
        Find keycap emoji for number words.
        
        Args:
            word: Number word like "one", "two", etc.
            
        Returns:
            Tuple of (emoji, category) or ('', '') if not found
        """
        word_lower = word.lower()
        
        if word_lower not in NUMBER_WORDS:
            return '', ''
        
        digit = NUMBER_WORDS[word_lower]
        
        # Search for keycap emoji with this digit
        for emoji, metadata in self.emoji_metadata.items():
            text = metadata.get('text', '').lower()
            keywords = metadata.get('keywords', [])
            
            # Check if this is a keycap for our digit
            if 'keycap' in text:
                if digit in keywords or digit in text:
                    return (
                        emoji,
                        metadata.get('category', ''),
                    )
        
        return '', ''
    
    def find_best_emoji(self, word: str, definition: str = "", 
                        synonyms: List[str] = None,
                        pos: str = "") -> Tuple[str, str]:
        """
        Find the best emoji for a word.
        
        Matching strategy:
        1. For number words, find the corresponding keycap emoji
        2. Search keyword index for direct matches
        3. When multiple emojis share a keyword, use text field to pick most generic
        4. Fall back to synonym matching if no direct match
        
        Note: Category is only returned for nouns. For verbs, adjectives, and adverbs,
        emoji categories don't make semantic sense, so empty string is returned.
        
        Returns:
            Tuple of (emoji, category) or ('', '') if no match
        """
        if not self._fetched:
            self.fetch()
        
        word_lower = word.lower().strip()
        synonyms = synonyms or []
        
        # Strategy 1: Handle number words specially
        if word_lower in NUMBER_WORDS:
            result = self._find_number_keycap(word_lower)
            if result[0]:
                # Numbers are nouns, so include category
                return result
        
        # Strategy 2: Direct keyword match
        if word_lower in self.keyword_index:
            candidates = self.keyword_index[word_lower]
            
            # Filter out flag emojis for common words
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
                # Only include category for nouns
                category = metadata.get('category', '') if pos == 'noun' else ''
                return (emoji, category)
        
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
                        return (emoji, category)
        
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
                        return (emoji, category)
        
        # No match found
        return '', ''
    
    def _get_word_variations(self, word: str) -> List[str]:
        """Generate word variations (plural, verb forms, etc.)."""
        variations = []
        
        # Singular/plural
        if word.endswith('s'):
            variations.append(word[:-1])
            if word.endswith('es'):
                variations.append(word[:-2])
            if word.endswith('ies'):
                variations.append(word[:-3] + 'y')
        else:
            variations.append(word + 's')
            variations.append(word + 'es')
        
        # Verb forms
        if word.endswith('ing'):
            base = word[:-3]
            variations.append(base)
            variations.append(base + 'e')
        elif word.endswith('ed'):
            base = word[:-2]
            variations.append(base)
            variations.append(base + 'e')
            if word.endswith('ied'):
                variations.append(word[:-3] + 'y')
        else:
            variations.append(word + 'ing')
            variations.append(word + 'ed')
        
        # Adjective forms
        if word.endswith('ly'):
            variations.append(word[:-2])
        if word.endswith('er'):
            variations.append(word[:-2])
            variations.append(word[:-1])
        if word.endswith('est'):
            variations.append(word[:-3])
        
        return [v for v in variations if len(v) >= 2]
    
    def get_category_for_emoji(self, emoji: str) -> str:
        """Get category for an emoji."""
        if not self._fetched:
            self.fetch()
        
        meta = self.emoji_metadata.get(emoji, {})
        return meta.get('category', '')
    
    def get_category_for_word(self, word: str, pos: str = 'noun') -> Optional[str]:
        """
        Get a category for a word based on its emoji match.
        
        This is primarily useful for nouns. For verbs, adjectives, and adverbs,
        emoji categories may not be meaningful.
        
        Args:
            word: The word to categorize
            pos: Part of speech
            
        Returns:
            Category string or None if not applicable
        """
        if pos not in ['noun']:
            # Categories from emojis are primarily meaningful for nouns
            return None
        
        emoji, category, subcategory = self.find_best_emoji(word, pos=pos)
        
        if category:
            return category
        
        return None
    
    def search(self, query: str, limit: int = 30) -> List[Dict]:
        """Search for emojis matching a query."""
        if not self._fetched:
            self.fetch()
        
        query_lower = query.lower().strip()
        if not query_lower:
            return []
        
        results = []
        seen = set()
        
        # Exact keyword match
        if query_lower in self.keyword_index:
            for emoji, meta in self.keyword_index[query_lower]:
                if emoji not in seen:
                    results.append(self._make_result(emoji, meta))
                    seen.add(emoji)
        
        # Partial keyword match
        for keyword in self.keyword_index:
            if query_lower in keyword and keyword != query_lower:
                for emoji, meta in self.keyword_index[keyword][:2]:
                    if emoji not in seen:
                        results.append(self._make_result(emoji, meta))
                        seen.add(emoji)
        
        # Text field match
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

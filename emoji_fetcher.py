"""
Emoji data fetcher with intelligent matching algorithm.

Combines two sources with fallback:
1. Primary: BehrouzSohrabi/Emoji for categories, text descriptions, and keywords
2. Fallback: iamcal/emoji-data + muan/emojilib when target word not in primary

The matching algorithm uses multiple strategies to find the best emoji:
- Direct keyword match with scoring
- Definition word matching
- Synonym matching
- Word variations
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
    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
    'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
}


class EmojiFetcher:
    """
    Fetches and matches emoji data with intelligent fallback strategy.
    """
    
    def __init__(self):
        # Primary source (BehrouzSohrabi)
        self.primary_metadata: Dict[str, Dict] = {}
        self.primary_keyword_index: Dict[str, List[Tuple[str, Dict]]] = defaultdict(list)
        
        # Fallback source (iamcal + emojilib)
        self.fallback_metadata: Dict[str, Dict] = {}
        self.fallback_keywords: Dict[str, List[str]] = {}
        self.fallback_keyword_index: Dict[str, List[Tuple[str, int, Dict]]] = defaultdict(list)
        
        self._primary_fetched = False
        self._fallback_fetched = False
    
    def fetch(self) -> bool:
        """Fetch emoji data, starting with primary source."""
        if self._primary_fetched:
            return True
        
        # Try cache first
        cached = cache_get("emoji_unified_v1")
        if cached:
            self.primary_metadata = cached.get('primary_metadata', {})
            self.fallback_metadata = cached.get('fallback_metadata', {})
            self.fallback_keywords = cached.get('fallback_keywords', {})
            self._build_primary_index()
            self._build_fallback_index()
            self._primary_fetched = True
            self._fallback_fetched = True
            return True
        
        # Fetch primary source
        success = self._fetch_primary()
        
        # Always fetch fallback to have comprehensive coverage
        if success:
            self._fetch_fallback()
        
        # Cache everything
        if self._primary_fetched or self._fallback_fetched:
            cache_set("emoji_unified_v1", {
                'primary_metadata': self.primary_metadata,
                'fallback_metadata': self.fallback_metadata,
                'fallback_keywords': self.fallback_keywords,
            })
        
        return self._primary_fetched or self._fallback_fetched
    
    def _fetch_primary(self) -> bool:
        """Fetch from BehrouzSohrabi/Emoji source."""
        print("😀 Fetching emoji data from BehrouzSohrabi/Emoji...")
        
        try:
            resp = requests.get(URLS['emoji_categories'], timeout=30)
            resp.raise_for_status()
            emoji_data = resp.json()
            
            if not isinstance(emoji_data, dict):
                print(f"   ⚠ Unexpected data format")
                return False
            
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
                    
                    self.primary_metadata[emoji_char] = {
                        'text': text,
                        'keywords': keywords,
                        'category': category,
                    }
            
            if len(self.primary_metadata) == 0:
                print(f"   ⚠ No emoji entries loaded from primary source")
                return False
            
            print(f"   ✓ Loaded {len(self.primary_metadata)} emoji entries from primary")
            
            self._build_primary_index()
            self._primary_fetched = True
            return True
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch primary emoji data: {e}")
            return False
    
    def _fetch_fallback(self) -> bool:
        """Fetch from iamcal/emoji-data + muan/emojilib sources."""
        print("   📦 Fetching fallback emoji data...")
        
        try:
            # Fetch emoji-data for categories
            resp = requests.get(URLS['emoji_data'], timeout=30)
            resp.raise_for_status()
            emoji_data_list = resp.json()
            
            for item in emoji_data_list:
                unified = item.get('unified', '')
                try:
                    emoji_char = ''.join(
                        chr(int(code, 16)) for code in unified.split('-')
                    )
                except (ValueError, OverflowError):
                    continue
                
                self.fallback_metadata[emoji_char] = {
                    'name': item.get('name', ''),
                    'short_name': item.get('short_name', ''),
                    'category': item.get('category', ''),
                    'subcategory': item.get('subcategory', ''),
                }
            
            time.sleep(API_DELAY)
            
            # Fetch emojilib for keywords
            resp = requests.get(URLS['emojilib'], timeout=30)
            resp.raise_for_status()
            emojilib_data = resp.json()
            
            for emoji_char, keywords in emojilib_data.items():
                if isinstance(keywords, list) and keywords:
                    self.fallback_keywords[emoji_char] = keywords
            
            print(f"   ✓ Loaded {len(self.fallback_metadata)} emoji entries from fallback")
            
            self._build_fallback_index()
            self._fallback_fetched = True
            return True
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch fallback data: {e}")
            return False
    
    def _build_primary_index(self):
        """Build reverse index for primary source."""
        self.primary_keyword_index = defaultdict(list)
        
        for emoji_char, metadata in self.primary_metadata.items():
            keywords = metadata.get('keywords', [])
            
            for keyword in keywords:
                keyword_lower = keyword.lower().strip()
                if keyword_lower:
                    self.primary_keyword_index[keyword_lower].append((emoji_char, metadata))
    
    def _build_fallback_index(self):
        """Build reverse index for fallback source."""
        self.fallback_keyword_index = defaultdict(list)
        
        for emoji_char, keywords in self.fallback_keywords.items():
            metadata = self.fallback_metadata.get(emoji_char, {})
            
            for idx, keyword in enumerate(keywords):
                keyword_lower = keyword.lower().replace('_', ' ').replace('-', ' ')
                self.fallback_keyword_index[keyword_lower].append((emoji_char, idx, metadata))
                
                # Index individual words from multi-word keywords
                words = keyword_lower.split()
                if len(words) > 1:
                    for word in words:
                        if len(word) >= 3 and word not in EXCLUDED_WORDS:
                            self.fallback_keyword_index[word].append((emoji_char, idx + 100, metadata))
        
        # Sort by position
        for keyword in self.fallback_keyword_index:
            self.fallback_keyword_index[keyword].sort(key=lambda x: x[1])
    
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
        
        # Search primary first
        for emoji, metadata in self.primary_metadata.items():
            text = metadata.get('text', '').lower()
            keywords = metadata.get('keywords', [])
            
            if 'keycap' in text:
                if digit in keywords or digit in text:
                    return emoji, metadata.get('category', '')
        
        # Search fallback
        for emoji, keywords in self.fallback_keywords.items():
            if 'keycap' in ' '.join(keywords).lower():
                if digit in keywords or any(digit in k for k in keywords):
                    meta = self.fallback_metadata.get(emoji, {})
                    return emoji, meta.get('category', '')
        
        return '', ''
    
    def find_best_emoji(self, word: str, definition: str = "", 
                        synonyms: List[str] = None,
                        pos: str = "") -> Tuple[str, str]:
        """
        Find the best emoji for a word using unified approach.
        
        Strategy:
        1. Check for number words (keycap emojis)
        2. Try primary source (BehrouzSohrabi) with keyword matching
        3. If no match, try fallback source (iamcal/emojilib) with advanced scoring
        4. Try word variations and synonyms
        
        Returns:
            Tuple of (emoji, category) or ('', '') if no match
        """
        if not self._primary_fetched and not self._fallback_fetched:
            self.fetch()
        
        word_lower = word.lower().strip()
        synonyms = synonyms or []
        
        # Strategy 1: Handle number words
        if word_lower in NUMBER_WORDS:
            result = self._find_number_keycap(word_lower)
            if result[0]:
                return result
        
        # Strategy 2: Try primary source first
        if self._primary_fetched:
            result = self._search_primary(word_lower, pos)
            if result[0]:
                return result
            
            # Try variations in primary
            variations = self._get_word_variations(word_lower)
            for var in variations:
                if var in self.primary_keyword_index and var != word_lower:
                    candidates = self.primary_keyword_index[var]
                    non_flag = [(e, m) for e, m in candidates if m.get('category', '') != 'Flags']
                    
                    if non_flag:
                        emoji, metadata = self._find_most_generic_emoji(non_flag, var)
                        if emoji:
                            category = metadata.get('category', '') if pos == 'noun' else ''
                            return emoji, category
        
        # Strategy 3: Fallback to secondary source
        if self._fallback_fetched:
            result = self._search_fallback(word_lower, definition, synonyms, pos)
            if result[0]:
                return result
        
        # Strategy 4: Try synonyms in primary source
        if self._primary_fetched:
            for syn in synonyms[:5]:
                syn_lower = syn.lower()
                if syn_lower in self.primary_keyword_index:
                    candidates = self.primary_keyword_index[syn_lower]
                    non_flag = [(e, m) for e, m in candidates if m.get('category', '') != 'Flags']
                    
                    if non_flag:
                        emoji, metadata = self._find_most_generic_emoji(non_flag, syn_lower)
                        if emoji:
                            category = metadata.get('category', '') if pos == 'noun' else ''
                            return emoji, category
        
        return '', ''
    
    def _search_primary(self, word: str, pos: str) -> Tuple[str, str]:
        """Search in primary source."""
        if word in self.primary_keyword_index:
            candidates = self.primary_keyword_index[word]
            
            non_flag_candidates = [
                (e, m) for e, m in candidates 
                if m.get('category', '') != 'Flags'
            ]
            
            if non_flag_candidates:
                emoji, metadata = self._find_most_generic_emoji(non_flag_candidates, word)
            elif candidates:
                emoji, metadata = self._find_most_generic_emoji(candidates, word)
            else:
                return '', ''
            
            if emoji:
                category = metadata.get('category', '') if pos == 'noun' else ''
                return emoji, category
        
        return '', ''
    
    def _search_fallback(self, word: str, definition: str, 
                         synonyms: List[str], pos: str) -> Tuple[str, str]:
        """Search in fallback source with advanced scoring."""
        candidates: Dict[str, Dict] = defaultdict(lambda: {
            'score': 0, 
            'meta': {}, 
            'is_flag': False,
            'first_word_match': False
        })
        
        # Direct keyword match
        if word in self.fallback_keyword_index:
            for emoji, position, meta in self.fallback_keyword_index[word]:
                keywords = self.fallback_keywords.get(emoji, [])
                is_flag = meta.get('category', '') == 'Flags'
                
                exact_match = any(
                    kw.lower().replace('_', ' ').replace('-', ' ') == word 
                    for kw in keywords
                )
                
                # Check first keyword first word
                first_word_match = False
                if keywords:
                    first_kw_words = keywords[0].lower().replace('_', ' ').split()
                    first_word_match = (first_kw_words[0] == word if first_kw_words else False)
                
                base_score = max(100 - (position * 10), 10)
                score = 0
                
                if first_word_match:
                    score += 500 + base_score
                    candidates[emoji]['first_word_match'] = True
                elif exact_match and position == 0:
                    score += 300 + base_score
                elif exact_match:
                    score += 150 + base_score
                else:
                    score += base_score // 2
                
                if is_flag:
                    score -= 200
                
                candidates[emoji]['score'] = max(candidates[emoji]['score'], score)
                candidates[emoji]['meta'] = meta
                candidates[emoji]['is_flag'] = is_flag
        
        # Definition matching
        if definition and max((c['score'] for c in candidates.values()), default=0) < 150:
            def_words = self._extract_content_words(definition)
            for def_word in def_words:
                if def_word in self.fallback_keyword_index:
                    for emoji, position, meta in self.fallback_keyword_index[def_word][:3]:
                        is_flag = meta.get('category', '') == 'Flags'
                        score = max(30 - (position * 5), 5)
                        if is_flag:
                            score -= 50
                        
                        candidates[emoji]['score'] += score
                        if not candidates[emoji]['meta']:
                            candidates[emoji]['meta'] = meta
                            candidates[emoji]['is_flag'] = is_flag
        
        # Synonym matching
        for syn in synonyms[:5]:
            syn_lower = syn.lower()
            if syn_lower in self.fallback_keyword_index:
                for emoji, position, meta in self.fallback_keyword_index[syn_lower][:3]:
                    is_flag = meta.get('category', '') == 'Flags'
                    score = max(40 - (position * 5), 5)
                    if is_flag:
                        score -= 50
                    
                    candidates[emoji]['score'] += score
                    if not candidates[emoji]['meta']:
                        candidates[emoji]['meta'] = meta
                        candidates[emoji]['is_flag'] = is_flag
        
        # Select best candidate
        min_score = 50
        non_flag_candidates = {
            e: d for e, d in candidates.items() 
            if d['score'] >= min_score and not d['is_flag']
        }
        
        if non_flag_candidates:
            filtered_candidates = non_flag_candidates
        else:
            filtered_candidates = {
                e: d for e, d in candidates.items()
                if d['score'] >= min_score
            }
        
        if not filtered_candidates:
            return '', ''
        
        best_emoji = max(filtered_candidates.keys(), 
                        key=lambda e: filtered_candidates[e]['score'])
        meta = filtered_candidates[best_emoji]['meta']
        
        category = meta.get('category', '') if pos == 'noun' else ''
        return best_emoji, category
    
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
            if word.endswith('ied'):
                variations.append(word[:-3] + 'y')
        else:
            variations.append(word + 'ing')
            variations.append(word + 'ed')
        
        if word.endswith('ly'):
            variations.append(word[:-2])
        if word.endswith('er'):
            variations.append(word[:-2])
            variations.append(word[:-1])
        if word.endswith('est'):
            variations.append(word[:-3])
        
        return [v for v in variations if len(v) >= 2]
    
    def _extract_content_words(self, text: str) -> Set[str]:
        """Extract meaningful content words from text."""
        words = set(re.findall(r'\b[a-z]{3,}\b', text.lower()))
        words -= EXCLUDED_WORDS
        return words
    
    def search(self, query: str, limit: int = 30) -> List[Dict]:
        """Search for emojis matching a query."""
        if not self._primary_fetched and not self._fallback_fetched:
            self.fetch()
        
        query_lower = query.lower().strip()
        if not query_lower:
            return []
        
        results = []
        seen = set()
        
        # Search primary first
        if self._primary_fetched:
            if query_lower in self.primary_keyword_index:
                for emoji, meta in self.primary_keyword_index[query_lower]:
                    if emoji not in seen:
                        results.append({
                            'emoji': emoji,
                            'name': meta.get('text', ''),
                            'keywords': meta.get('keywords', [])[:5],
                            'category': meta.get('category', ''),
                        })
                        seen.add(emoji)
        
        # Search fallback
        if self._fallback_fetched and len(results) < limit:
            if query_lower in self.fallback_keyword_index:
                for emoji, position, meta in self.fallback_keyword_index[query_lower]:
                    if emoji not in seen:
                        keywords = self.fallback_keywords.get(emoji, [])
                        results.append({
                            'emoji': emoji,
                            'name': keywords[0] if keywords else meta.get('short_name', ''),
                            'keywords': keywords[:5],
                            'category': meta.get('category', ''),
                        })
                        seen.add(emoji)
        
        return results[:limit]
    
    def get_all_categories(self) -> List[str]:
        """Get all unique categories."""
        if not self._primary_fetched and not self._fallback_fetched:
            self.fetch()
        
        categories = set()
        
        for meta in self.primary_metadata.values():
            cat = meta.get('category', '')
            if cat:
                categories.add(cat)
        
        for meta in self.fallback_metadata.values():
            cat = meta.get('category', '')
            if cat:
                categories.add(cat)
        
        return sorted(categories)
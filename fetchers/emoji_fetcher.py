"""
Emoji data fetcher with intelligent matching algorithm.

Fetches from:
- iamcal/emoji-data for categories and subcategories
- muan/emojilib for keyword matching

The matching algorithm uses multiple strategies to find the best emoji:
1. Direct keyword match with scoring
2. Definition word matching
3. Cross-reference between emojilib keywords and emoji-data categories

Refinements for better matching:
- First keyword bonus: emoji's first keyword = primary meaning
- Flag deprioritization: country flags often collide with common words
- Semantic density: prefer emojis with more related keywords
"""

import re
import time
import requests
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict

from ..config import URLS, API_DELAY, EXCLUDED_WORDS
from ..utils.cache import cache_get, cache_set


class EmojiFetcher:
    """
    Fetches and matches emoji data from external sources.
    
    No fallback emojis - if no match is found, returns empty string.
    """
    
    def __init__(self):
        # emoji-data: emoji char -> metadata (category, subcategory, etc.)
        self.emoji_metadata: Dict[str, Dict] = {}
        
        # emojilib: emoji char -> list of keywords
        self.emoji_keywords: Dict[str, List[str]] = {}
        
        # Reverse index: keyword -> list of (emoji, position, metadata)
        self.keyword_index: Dict[str, List[Tuple[str, int, Dict]]] = defaultdict(list)
        
        # Unified code -> emoji char mapping
        self.unified_to_emoji: Dict[str, str] = {}
        
        self._fetched = False
    
    def fetch(self) -> bool:
        """Fetch emoji data from both sources."""
        if self._fetched:
            return True
        
        # Try cache first
        cached = cache_get("emoji_combined_v2")
        if cached:
            self.emoji_metadata = cached.get('metadata', {})
            self.emoji_keywords = cached.get('keywords', {})
            self.unified_to_emoji = cached.get('unified_map', {})
            self._build_keyword_index()
            self._fetched = True
            return True
        
        print("😀 Fetching emoji data...")
        
        # Step 1: Fetch emoji-data (categories, subcategories, unified codes)
        try:
            resp = requests.get(URLS['emoji_data'], timeout=30)
            resp.raise_for_status()
            emoji_data_list = resp.json()
            
            for item in emoji_data_list:
                unified = item.get('unified', '')
                
                # Convert unified code to emoji character
                try:
                    emoji_char = ''.join(
                        chr(int(code, 16)) for code in unified.split('-')
                    )
                except (ValueError, OverflowError):
                    continue
                
                self.unified_to_emoji[unified] = emoji_char
                
                self.emoji_metadata[emoji_char] = {
                    'name': item.get('name', ''),
                    'short_name': item.get('short_name', ''),
                    'short_names': item.get('short_names', []),
                    'category': item.get('category', ''),
                    'subcategory': item.get('subcategory', ''),
                    'unified': unified,
                }
            
            print(f"   ✓ Loaded {len(self.emoji_metadata)} emoji metadata entries")
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch emoji-data: {e}")
            return False
        
        time.sleep(API_DELAY)
        
        # Step 2: Fetch emojilib (keywords)
        try:
            resp = requests.get(URLS['emojilib'], timeout=30)
            resp.raise_for_status()
            emojilib_data = resp.json()
            
            for emoji_char, keywords in emojilib_data.items():
                if isinstance(keywords, list) and keywords:
                    self.emoji_keywords[emoji_char] = keywords
            
            print(f"   ✓ Loaded {len(self.emoji_keywords)} emoji keyword entries")
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch emojilib: {e}")
            return False
        
        # Build index and cache
        self._build_keyword_index()
        
        cache_set("emoji_combined_v2", {
            'metadata': self.emoji_metadata,
            'keywords': self.emoji_keywords,
            'unified_map': self.unified_to_emoji,
        })
        
        self._fetched = True
        return True
    
    def _build_keyword_index(self):
        """Build reverse index from keywords to emojis with position tracking."""
        self.keyword_index = defaultdict(list)
        
        for emoji_char, keywords in self.emoji_keywords.items():
            metadata = self.emoji_metadata.get(emoji_char, {})
            
            for idx, keyword in enumerate(keywords):
                # Normalize keyword
                keyword_lower = keyword.lower().replace('_', ' ').replace('-', ' ')
                
                # Add to index with position
                self.keyword_index[keyword_lower].append((emoji_char, idx, metadata))
                
                # Also index individual words from multi-word keywords
                words = keyword_lower.split()
                if len(words) > 1:
                    for word in words:
                        if len(word) >= 3 and word not in EXCLUDED_WORDS:
                            # Higher position for partial matches
                            self.keyword_index[word].append((emoji_char, idx + 100, metadata))
        
        # Sort each keyword's emojis by position (lowest first)
        for keyword in self.keyword_index:
            self.keyword_index[keyword].sort(key=lambda x: x[1])
    
    def _get_first_keyword_word(self, emoji: str) -> str:
        """
        Get the first meaningful word from an emoji's first keyword.
        
        For example:
        - "new_button" -> "new"
        - "page_facing_up" -> "page"
        - "prohibited" -> "prohibited"
        """
        keywords = self.emoji_keywords.get(emoji, [])
        if not keywords:
            return ''
        
        first_kw = keywords[0].lower().replace('_', ' ').replace('-', ' ')
        words = first_kw.split()
        return words[0] if words else ''
    
    def _count_semantic_matches(self, emoji: str, word: str) -> int:
        """
        Count how many keywords for this emoji relate to the target word.
        
        This helps identify emojis that are semantically focused on the concept.
        """
        keywords = self.emoji_keywords.get(emoji, [])
        count = 0
        word_lower = word.lower()
        
        for kw in keywords:
            kw_lower = kw.lower().replace('_', ' ').replace('-', ' ')
            if word_lower in kw_lower or kw_lower in word_lower:
                count += 1
        
        return count
    
    def find_best_emoji(self, word: str, definition: str = "", 
                        synonyms: List[str] = None,
                        pos: str = "") -> Tuple[str, str, str]:
        """
        Find the best emoji for a word.
        
        Matching strategy with refinements:
        1. FIRST-KEYWORD PRIORITY: If word matches the first word of an emoji's 
           first keyword, that emoji is strongly preferred (e.g., "new" -> 🆕 "new_button")
        2. FLAG DEPRIORITIZATION: Flags category is penalized for common words
        3. SEMANTIC DENSITY: Prefer emojis with more keywords matching the concept
        4. POSITION SCORING: Earlier keyword position = higher relevance
        
        Returns:
            Tuple of (emoji, category, subcategory) or ('', '', '') if no match
        """
        if not self._fetched:
            self.fetch()
        
        word_lower = word.lower().strip()
        synonyms = synonyms or []
        
        # Track candidate emojis with detailed scoring
        candidates: Dict[str, Dict] = defaultdict(lambda: {
            'score': 0, 
            'meta': {}, 
            'match_type': '',
            'is_flag': False,
            'first_word_match': False
        })
        
        # Strategy 1: Direct keyword match with refined scoring
        if word_lower in self.keyword_index:
            for emoji, position, meta in self.keyword_index[word_lower]:
                keywords = self.emoji_keywords.get(emoji, [])
                is_flag = meta.get('category', '') == 'Flags'
                
                # Check if this is an exact keyword match
                exact_match = any(
                    kw.lower().replace('_', ' ').replace('-', ' ') == word_lower 
                    for kw in keywords
                )
                
                # Check if word matches the FIRST word of the FIRST keyword
                first_word = self._get_first_keyword_word(emoji)
                first_word_match = (first_word == word_lower)
                
                # Calculate base score from position
                # Position 0 = 100, decreasing by 10 for each position
                base_score = max(100 - (position * 10), 10)
                
                score = 0
                
                if first_word_match:
                    # Massive bonus for first-word match (e.g., "new" -> "new_button")
                    score += 500 + base_score
                    candidates[emoji]['first_word_match'] = True
                elif exact_match and position == 0:
                    # Strong bonus for exact match at position 0
                    score += 300 + base_score
                elif exact_match:
                    # Good bonus for exact match at any position
                    score += 150 + base_score
                else:
                    # Partial match (from multi-word keyword split)
                    score += base_score // 2
                
                # Semantic density bonus
                semantic_count = self._count_semantic_matches(emoji, word_lower)
                if semantic_count >= 3:
                    score += 50
                elif semantic_count >= 2:
                    score += 25
                
                # Flag penalty - flags often collide with common words
                if is_flag:
                    score -= 200
                
                candidates[emoji]['score'] = max(candidates[emoji]['score'], score)
                candidates[emoji]['meta'] = meta
                candidates[emoji]['is_flag'] = is_flag
        
        # Strategy 2: Word variations (only if no strong matches found)
        best_current = max((c['score'] for c in candidates.values()), default=0)
        
        if best_current < 200:
            variations = self._get_word_variations(word_lower)
            for var in variations:
                if var in self.keyword_index and var != word_lower:
                    for emoji, position, meta in self.keyword_index[var][:5]:
                        if candidates[emoji]['score'] > 0:
                            continue  # Already scored
                        
                        keywords = self.emoji_keywords.get(emoji, [])
                        exact_match = any(
                            kw.lower().replace('_', ' ').replace('-', ' ') == var 
                            for kw in keywords
                        )
                        
                        is_flag = meta.get('category', '') == 'Flags'
                        
                        if exact_match:
                            score = max(80 - (position * 10), 10)
                            if is_flag:
                                score -= 100
                            
                            candidates[emoji]['score'] = score
                            candidates[emoji]['meta'] = meta
                            candidates[emoji]['is_flag'] = is_flag
        
        # Strategy 3: Definition analysis (only if no good matches yet)
        best_current = max((c['score'] for c in candidates.values()), default=0)
        
        if definition and best_current < 150:
            def_words = self._extract_content_words(definition)
            def_words = {w for w in def_words if len(w) >= 4}
            
            emoji_def_matches: Dict[str, Set[str]] = defaultdict(set)
            
            for def_word in def_words:
                if def_word in self.keyword_index:
                    for emoji, position, meta in self.keyword_index[def_word][:3]:
                        keywords = self.emoji_keywords.get(emoji, [])
                        if any(kw.lower().replace('_', ' ') == def_word for kw in keywords):
                            emoji_def_matches[emoji].add(def_word)
                            
                            is_flag = meta.get('category', '') == 'Flags'
                            score = max(30 - (position * 5), 5)
                            if is_flag:
                                score -= 50
                            
                            candidates[emoji]['score'] += score
                            if not candidates[emoji]['meta']:
                                candidates[emoji]['meta'] = meta
                                candidates[emoji]['is_flag'] = is_flag
            
            # Bonus for multiple definition word matches
            for emoji, matched_words in emoji_def_matches.items():
                if len(matched_words) >= 2:
                    candidates[emoji]['score'] += 20 * len(matched_words)
        
        # Strategy 4: Synonym matching
        for syn in synonyms[:5]:
            syn_lower = syn.lower()
            if syn_lower in self.keyword_index:
                for emoji, position, meta in self.keyword_index[syn_lower][:3]:
                    keywords = self.emoji_keywords.get(emoji, [])
                    if any(kw.lower().replace('_', ' ') == syn_lower for kw in keywords):
                        is_flag = meta.get('category', '') == 'Flags'
                        score = max(40 - (position * 5), 5)
                        if is_flag:
                            score -= 50
                        
                        candidates[emoji]['score'] += score
                        if not candidates[emoji]['meta']:
                            candidates[emoji]['meta'] = meta
                            candidates[emoji]['is_flag'] = is_flag
        
        # Filter and select best candidate
        min_score = 50
        
        # Prefer non-flag candidates if they have reasonable scores
        non_flag_candidates = {
            e: d for e, d in candidates.items() 
            if d['score'] >= min_score and not d['is_flag']
        }
        
        if non_flag_candidates:
            filtered_candidates = non_flag_candidates
        else:
            # Fall back to all candidates including flags
            filtered_candidates = {
                e: d for e, d in candidates.items()
                if d['score'] >= min_score
            }
        
        if not filtered_candidates:
            return '', '', ''
        
        # Find best candidate by score
        best_emoji = max(filtered_candidates.keys(), key=lambda e: filtered_candidates[e]['score'])
        meta = filtered_candidates[best_emoji]['meta']
        
        return (
            best_emoji,
            meta.get('category', ''),
            meta.get('subcategory', '')
        )
    
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
    
    def _extract_content_words(self, text: str) -> Set[str]:
        """Extract meaningful content words from text."""
        words = set(re.findall(r'\b[a-z]{3,}\b', text.lower()))
        words -= EXCLUDED_WORDS
        return words
    
    def get_category_for_emoji(self, emoji: str) -> Tuple[str, str]:
        """Get category and subcategory for an emoji."""
        if not self._fetched:
            self.fetch()
        
        meta = self.emoji_metadata.get(emoji, {})
        return meta.get('category', ''), meta.get('subcategory', '')
    
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
            for emoji, position, meta in self.keyword_index[query_lower]:
                if emoji not in seen:
                    results.append(self._make_result(emoji, meta))
                    seen.add(emoji)
        
        for keyword in self.keyword_index:
            if query_lower in keyword and keyword != query_lower:
                for emoji, position, meta in self.keyword_index[keyword][:2]:
                    if emoji not in seen:
                        results.append(self._make_result(emoji, meta))
                        seen.add(emoji)
        
        return results[:limit]
    
    def _make_result(self, emoji: str, meta: Dict) -> Dict:
        """Create a search result dict."""
        keywords = self.emoji_keywords.get(emoji, [])
        return {
            'emoji': emoji,
            'name': keywords[0] if keywords else meta.get('short_name', ''),
            'keywords': keywords[:5],
            'category': meta.get('category', ''),
            'subcategory': meta.get('subcategory', ''),
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

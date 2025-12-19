"""
Emoji data fetcher with intelligent matching algorithm.

Fetches from:
- iamcal/emoji-data for categories and subcategories
- muan/emojilib for keyword matching

The matching algorithm uses multiple strategies to find the best emoji:
1. Direct keyword match with scoring
2. Definition word matching
3. Cross-reference between emojilib keywords and emoji-data categories
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
        
        # Reverse index: keyword -> list of (emoji, score, metadata)
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
        """Build reverse index from keywords to emojis with scoring."""
        self.keyword_index = defaultdict(list)
        
        for emoji_char, keywords in self.emoji_keywords.items():
            metadata = self.emoji_metadata.get(emoji_char, {})
            
            for idx, keyword in enumerate(keywords):
                # Score based on position (first = highest relevance)
                # First keyword gets score 100, decreasing by 10 for each position
                score = max(100 - (idx * 10), 10)
                
                # Normalize keyword
                keyword_lower = keyword.lower().replace('_', ' ').replace('-', ' ')
                
                # Add to index
                self.keyword_index[keyword_lower].append((emoji_char, score, metadata))
                
                # Also index individual words from multi-word keywords
                words = keyword_lower.split()
                if len(words) > 1:
                    for word in words:
                        if len(word) >= 3 and word not in EXCLUDED_WORDS:
                            # Lower score for partial matches
                            self.keyword_index[word].append((emoji_char, score // 3, metadata))
        
        # Sort each keyword's emojis by score (highest first)
        for keyword in self.keyword_index:
            self.keyword_index[keyword].sort(key=lambda x: -x[1])
    
    def find_best_emoji(self, word: str, definition: str = "", 
                        synonyms: List[str] = None,
                        pos: str = "") -> Tuple[str, str, str]:
        """
        Find the best emoji for a word.
        
        Uses multiple strategies with careful filtering to avoid wrong matches:
        1. Direct keyword match on word (exact match preferred)
        2. Match on word variations (plural, verb forms)
        3. Match on definition words + word overlap scoring
        4. Match on synonyms
        
        Filters out:
        - Partial matches that are substrings (e.g., "not" matching "note")
        - Category mismatches based on POS
        
        Returns:
            Tuple of (emoji, category, subcategory) or ('', '', '') if no match
        """
        if not self._fetched:
            self.fetch()
        
        word_lower = word.lower().strip()
        synonyms = synonyms or []
        
        # Track candidate emojis with scores
        candidates: Dict[str, Dict] = defaultdict(lambda: {'score': 0, 'meta': {}, 'match_type': ''})
        
        # Strategy 1: Direct EXACT match on word (highest priority)
        if word_lower in self.keyword_index:
            for emoji, score, meta in self.keyword_index[word_lower]:
                # Check if this is an exact keyword match (not substring)
                keywords = self.emoji_keywords.get(emoji, [])
                exact_match = any(
                    kw.lower().replace('_', ' ').replace('-', ' ') == word_lower 
                    for kw in keywords
                )
                
                if exact_match:
                    # Very high score for exact matches
                    candidates[emoji]['score'] += score * 5
                    candidates[emoji]['meta'] = meta
                    candidates[emoji]['match_type'] = 'exact'
                else:
                    # Lower score for partial matches
                    candidates[emoji]['score'] += score
                    if not candidates[emoji]['meta']:
                        candidates[emoji]['meta'] = meta
        
        # Strategy 2: Word variations (only if no exact matches found)
        exact_matches = [e for e, d in candidates.items() if d.get('match_type') == 'exact']
        
        if not exact_matches:
            variations = self._get_word_variations(word_lower)
            for var in variations:
                if var in self.keyword_index and var != word_lower:
                    for emoji, score, meta in self.keyword_index[var][:5]:
                        # Check for exact variation match
                        keywords = self.emoji_keywords.get(emoji, [])
                        exact_match = any(
                            kw.lower().replace('_', ' ').replace('-', ' ') == var 
                            for kw in keywords
                        )
                        
                        if exact_match:
                            candidates[emoji]['score'] += score * 3
                        else:
                            candidates[emoji]['score'] += score
                        
                        if not candidates[emoji]['meta']:
                            candidates[emoji]['meta'] = meta
        
        # Strategy 3: Definition analysis (only meaningful words)
        if definition:
            def_words = self._extract_content_words(definition)
            
            # Filter out words that might cause false matches
            def_words = {w for w in def_words if len(w) >= 4}  # Longer words only
            
            # Score emojis that match multiple definition words higher
            emoji_def_matches: Dict[str, Set[str]] = defaultdict(set)
            
            for def_word in def_words:
                if def_word in self.keyword_index:
                    for emoji, score, meta in self.keyword_index[def_word][:3]:
                        # Only count if it's an exact keyword match
                        keywords = self.emoji_keywords.get(emoji, [])
                        if any(kw.lower().replace('_', ' ') == def_word for kw in keywords):
                            emoji_def_matches[emoji].add(def_word)
                            candidates[emoji]['score'] += score // 2  # Lower weight for definition matches
                            if not candidates[emoji]['meta']:
                                candidates[emoji]['meta'] = meta
            
            # Bonus for emojis matching multiple definition words
            for emoji, matched_words in emoji_def_matches.items():
                if len(matched_words) >= 2:
                    candidates[emoji]['score'] += 30 * len(matched_words)
        
        # Strategy 4: Synonym matching (exact matches only)
        for syn in synonyms[:5]:
            syn_lower = syn.lower()
            if syn_lower in self.keyword_index:
                for emoji, score, meta in self.keyword_index[syn_lower][:3]:
                    # Only count exact matches
                    keywords = self.emoji_keywords.get(emoji, [])
                    if any(kw.lower().replace('_', ' ') == syn_lower for kw in keywords):
                        candidates[emoji]['score'] += score
                        if not candidates[emoji]['meta']:
                            candidates[emoji]['meta'] = meta
        
        # Filter candidates by relevance
        # Remove low-scoring candidates that might be false positives
        min_score = 50  # Minimum score threshold
        filtered_candidates = {
            e: d for e, d in candidates.items() 
            if d['score'] >= min_score
        }
        
        if not filtered_candidates:
            return '', '', ''
        
        # Find best candidate
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
            variations.append(word[:-1])  # Remove s
            if word.endswith('es'):
                variations.append(word[:-2])  # Remove es
            if word.endswith('ies'):
                variations.append(word[:-3] + 'y')  # cities -> city
        else:
            variations.append(word + 's')
            variations.append(word + 'es')
        
        # Verb forms
        if word.endswith('ing'):
            base = word[:-3]
            variations.append(base)
            variations.append(base + 'e')  # running -> run, baking -> bake
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
            variations.append(word[:-1])  # bigger -> big
        if word.endswith('est'):
            variations.append(word[:-3])
        
        return [v for v in variations if len(v) >= 2]
    
    def _extract_content_words(self, text: str) -> Set[str]:
        """Extract meaningful content words from text."""
        # Find all words 3+ characters
        words = set(re.findall(r'\b[a-z]{3,}\b', text.lower()))
        
        # Remove excluded words
        words -= EXCLUDED_WORDS
        
        return words
    
    def get_category_for_emoji(self, emoji: str) -> Tuple[str, str]:
        """
        Get category and subcategory for an emoji.
        
        Returns:
            Tuple of (category, subcategory) or ('', '') if not found
        """
        if not self._fetched:
            self.fetch()
        
        meta = self.emoji_metadata.get(emoji, {})
        return meta.get('category', ''), meta.get('subcategory', '')
    
    def search(self, query: str, limit: int = 30) -> List[Dict]:
        """
        Search for emojis matching a query.
        
        Returns list of dicts with emoji, name, keywords, category, subcategory.
        """
        if not self._fetched:
            self.fetch()
        
        query_lower = query.lower().strip()
        if not query_lower:
            return []
        
        results = []
        seen = set()
        
        # Direct keyword matches (sorted by score)
        if query_lower in self.keyword_index:
            for emoji, score, meta in self.keyword_index[query_lower]:
                if emoji not in seen:
                    results.append(self._make_result(emoji, meta))
                    seen.add(emoji)
        
        # Partial matches in keywords
        for keyword in self.keyword_index:
            if query_lower in keyword and keyword != query_lower:
                for emoji, score, meta in self.keyword_index[keyword][:2]:
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

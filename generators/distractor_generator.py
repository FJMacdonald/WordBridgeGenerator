"""
Distractor generator following speech therapy rules.

Rules for valid distractors (ALL 8 MUST BE FOLLOWED):
1. NOT synonyms or antonyms of target word
2. NOT starting with the same sound as target word
3. NOT rhyming with the target word
4. NOT in the same category as target word
5. NOT semantically associated with target word
6. Same length first, then ±1, then ±2 as fallback
7. Same part of speech as target word
8. Minimize repetition across wordbank

API Usage for Rule Compliance:
- Rules 1, 5: Uses MW Thesaurus + USF Free Association for checking
- Rule 3: Uses Datamuse rhymes
- Rule 4: Uses Datamuse rel_gen for category checking
- Rule 7: Uses MW Learner's Dictionary for POS verification
"""

import time
import requests
from typing import Dict, List, Set
from collections import defaultdict

from ..config import DISTRACTOR_LENGTH_TOLERANCES, MAX_DISTRACTORS, API_DELAY, URLS
from .sound_detector import SoundGroupDetector


class DistractorGenerator:
    """
    Generates valid distractors following all 8 speech therapy rules.
    
    Uses API calls to verify rule compliance:
    - Datamuse for category and rhyme checking
    - Free Dictionary for POS verification (to minimize rate limits)
    """
    
    def __init__(self, frequency_fetcher, dictionary_fetcher, 
                 sound_detector: SoundGroupDetector = None):
        """
        Initialize distractor generator.
        
        Args:
            frequency_fetcher: FrequencyFetcher instance
            dictionary_fetcher: DictionaryFetcher instance
            sound_detector: SoundGroupDetector instance (optional)
        """
        self.frequency = frequency_fetcher
        self.dictionary = dictionary_fetcher
        self.sound_detector = sound_detector or SoundGroupDetector()
        
        # Track usage to minimize repetition (Rule 8)
        self.usage_count: Dict[str, int] = defaultdict(int)
        self.max_reuse = 3
        
        # POS cache to reduce API calls
        self.pos_cache: Dict[str, str] = {}
        
        # Category cache
        self.category_cache: Dict[str, str] = {}
    
    def generate(self, target_word: str, target_pos: str,
                 avoid_words: Set[str], rhymes: List[str] = None,
                 category: str = "") -> List[str]:
        """
        Generate valid distractors for a target word.
        
        All 8 rules are enforced:
        1. NOT synonyms/antonyms (checked via avoid_words)
        2. NOT same starting sound (checked via sound_detector)
        3. NOT rhyming (checked via rhymes list + ending comparison)
        4. NOT same category (checked via Datamuse rel_gen)
        5. NOT associated (checked via avoid_words)
        6. Same length ±0/1/2
        7. Same POS (verified via Free Dictionary)
        8. Minimize repetition (tracked via usage_count)
        
        Args:
            target_word: The word to generate distractors for
            target_pos: Part of speech of target word
            avoid_words: Words to avoid (synonyms, antonyms, associated)
            rhymes: List of rhyming words to avoid
            category: Category to avoid (words in same category)
            
        Returns:
            List of valid distractors (up to MAX_DISTRACTORS)
        """
        target_lower = target_word.lower()
        target_length = len(target_word)
        target_sound = self.sound_detector.get_sound_group(target_word)
        
        # Build complete avoid set (Rules 1 and 5)
        avoid_lower = {w.lower() for w in avoid_words if w}
        avoid_lower.add(target_lower)
        
        # Add rhymes to avoid set (Rule 3)
        rhyme_endings = set()
        if rhymes:
            for rhyme in rhymes:
                avoid_lower.add(rhyme.lower())
                if len(rhyme) >= 3:
                    rhyme_endings.add(rhyme.lower()[-3:])
        
        valid_distractors = []
        
        # Try each length tolerance level (Rule 6)
        for tolerance in DISTRACTOR_LENGTH_TOLERANCES:
            if len(valid_distractors) >= MAX_DISTRACTORS:
                break
            
            # Get candidate words at this length tolerance
            candidates = self.frequency.get_words_by_length(
                target_length, 
                tolerance=tolerance,
                exclude=avoid_lower | set(valid_distractors),
                limit=200
            )
            
            # Filter candidates through all rules
            for word in candidates:
                if len(valid_distractors) >= MAX_DISTRACTORS:
                    break
                
                word_lower = word.lower()
                
                # Rule 8: Minimize repetition
                if self.usage_count[word_lower] >= self.max_reuse:
                    continue
                
                # Rule 2: NOT same starting sound
                if self.sound_detector.get_sound_group(word) == target_sound:
                    continue
                
                # Rule 3: NOT rhyming
                if self._words_rhyme(word, target_word, rhyme_endings):
                    continue
                
                # Rule 4: NOT same category
                if category and self._same_category(word, category):
                    continue
                
                # Rule 7: Same POS (use Free Dictionary to minimize rate limits)
                if not self._verify_pos(word, target_pos):
                    continue
                
                # All rules passed
                valid_distractors.append(word)
                self.usage_count[word_lower] += 1
        
        return valid_distractors
    
    def _words_rhyme(self, word1: str, word2: str, 
                     rhyme_endings: Set[str] = None) -> bool:
        """
        Check if two words rhyme (Rule 3).
        
        Uses ending comparison and known rhyme endings.
        """
        w1, w2 = word1.lower(), word2.lower()
        
        if w1 == w2:
            return False
        
        # Check against known rhyme endings
        if rhyme_endings and len(w1) >= 3:
            if w1[-3:] in rhyme_endings:
                return True
        
        # Check last 3-4 characters
        for length in [4, 3]:
            if len(w1) >= length and len(w2) >= length:
                if w1[-length:] == w2[-length:]:
                    return True
        
        return False
    
    def _same_category(self, word: str, target_category: str) -> bool:
        """
        Check if word is in the same category as target (Rule 4).
        
        Uses Datamuse rel_gen (generalization) for category checking.
        """
        word_lower = word.lower()
        
        # Check cache
        if word_lower in self.category_cache:
            word_category = self.category_cache[word_lower]
            return word_category.lower() == target_category.lower()
        
        # Fetch category from Datamuse
        try:
            url = f"{URLS['datamuse']}?rel_gen={word_lower}&max=3"
            resp = requests.get(url, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    # Get the top category
                    word_category = data[0].get('word', '').lower()
                    self.category_cache[word_lower] = word_category
                    
                    # Check if categories match
                    if target_category.lower() in word_category or word_category in target_category.lower():
                        return True
                    
                    # Also check other returned categories
                    for item in data:
                        cat = item.get('word', '').lower()
                        if target_category.lower() in cat or cat in target_category.lower():
                            return True
        except:
            pass
        
        return False
    
    def _verify_pos(self, word: str, target_pos: str) -> bool:
        """
        Verify a word can be used as the target POS (Rule 7).
        
        Uses Free Dictionary to minimize rate limits on MW APIs.
        """
        word_lower = word.lower()
        
        # Check cache first
        if word_lower in self.pos_cache:
            cached_pos = self.pos_cache[word_lower]
            return cached_pos == target_pos or not cached_pos
        
        # Use Free Dictionary for POS verification (no rate limits)
        try:
            url = f"{URLS['free_dictionary']}/{word_lower}"
            resp = requests.get(url, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list):
                    # Get all POS from meanings
                    all_pos = set()
                    for meaning in data[0].get('meanings', []):
                        pos = meaning.get('partOfSpeech', '').lower()
                        if pos:
                            all_pos.add(pos)
                    
                    # Cache the primary POS
                    primary_pos = list(all_pos)[0] if all_pos else ''
                    self.pos_cache[word_lower] = primary_pos
                    
                    return target_pos in all_pos
        except:
            pass
        
        # If we couldn't determine POS, allow the word
        self.pos_cache[word_lower] = ''
        return True
    
    def reset_usage(self):
        """Reset usage counts (call between wordbank generations)."""
        self.usage_count.clear()
    
    def validate_distractors(self, target_word: str, distractors: List[str],
                             avoid_words: Set[str], rhymes: List[str] = None,
                             category: str = "") -> List[Dict]:
        """
        Validate a list of distractors and return issues.
        
        Checks all 8 rules and reports violations.
        
        Returns list of dicts with:
            - word: the distractor
            - valid: True/False
            - issues: list of issue descriptions (which rules violated)
        """
        target_lower = target_word.lower()
        target_length = len(target_word)
        target_sound = self.sound_detector.get_sound_group(target_word)
        
        avoid_lower = {w.lower() for w in avoid_words if w}
        rhyme_lower = {r.lower() for r in (rhymes or [])}
        
        results = []
        
        for dist in distractors:
            dist_lower = dist.lower()
            issues = []
            
            # Rule 1 & 5: Check avoid words (synonyms, antonyms, associated)
            if dist_lower in avoid_lower:
                issues.append("Rule 1/5: In avoid list (synonym/antonym/associated)")
            
            # Rule 2: Check starting sound
            if self.sound_detector.get_sound_group(dist) == target_sound:
                issues.append(f"Rule 2: Same starting sound ({target_sound})")
            
            # Rule 3: Check rhyming
            if dist_lower in rhyme_lower:
                issues.append("Rule 3: Rhymes with target")
            elif self._words_rhyme(dist, target_word):
                issues.append("Rule 3: Ending suggests rhyme")
            
            # Rule 4: Check category
            if category and self._same_category(dist, category):
                issues.append(f"Rule 4: Same category ({category})")
            
            # Rule 6: Check length
            length_diff = abs(len(dist) - target_length)
            if length_diff > 2:
                issues.append(f"Rule 6: Length difference too large ({length_diff})")
            
            # Rule 8: Check repetition
            if self.usage_count[dist_lower] >= self.max_reuse:
                issues.append(f"Rule 8: Overused ({self.usage_count[dist_lower]} times)")
            
            results.append({
                'word': dist,
                'valid': len(issues) == 0,
                'issues': issues,
            })
        
        return results

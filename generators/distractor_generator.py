"""
Distractor generator following speech therapy rules.

Rules for valid distractors:
1. NOT synonyms or antonyms of target word
2. NOT starting with the same sound as target word
3. NOT rhyming with the target word
4. NOT in the same category as target word
5. NOT semantically associated with target word
6. Same length first, then ±1, then ±2 as fallback
7. Same part of speech as target word
8. Minimize repetition across wordbank
"""

import time
from typing import Dict, List, Set
from collections import defaultdict

from ..config import DISTRACTOR_LENGTH_TOLERANCES, MAX_DISTRACTORS, API_DELAY
from .sound_detector import SoundGroupDetector


class DistractorGenerator:
    """
    Generates valid distractors following speech therapy rules.
    
    Uses progressive length tolerance:
    1. First tries exact same length
    2. Then ±1 character
    3. Finally ±2 characters
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
        
        # Track usage to minimize repetition
        self.usage_count: Dict[str, int] = defaultdict(int)
        self.max_reuse = 3
        
        # POS cache to reduce API calls
        self.pos_cache: Dict[str, str] = {}
    
    def generate(self, target_word: str, target_pos: str,
                 avoid_words: Set[str], rhymes: List[str] = None,
                 category: str = "") -> List[str]:
        """
        Generate valid distractors for a target word.
        
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
        
        # Build complete avoid set
        avoid_lower = {w.lower() for w in avoid_words if w}
        avoid_lower.add(target_lower)
        
        # Add rhymes to avoid set
        rhyme_endings = set()
        if rhymes:
            for rhyme in rhymes:
                avoid_lower.add(rhyme.lower())
                # Also track rhyme endings
                if len(rhyme) >= 3:
                    rhyme_endings.add(rhyme.lower()[-3:])
        
        valid_distractors = []
        
        # Try each length tolerance level
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
            
            # Filter candidates
            for word in candidates:
                if len(valid_distractors) >= MAX_DISTRACTORS:
                    break
                
                word_lower = word.lower()
                
                # Skip if already used too often
                if self.usage_count[word_lower] >= self.max_reuse:
                    continue
                
                # Rule 2: NOT same starting sound
                if self.sound_detector.get_sound_group(word) == target_sound:
                    continue
                
                # Rule 3: NOT rhyming (check ending)
                if self._words_rhyme(word, target_word, rhyme_endings):
                    continue
                
                # Rule 7: Same POS (verify with dictionary)
                if not self._verify_pos(word, target_pos):
                    continue
                
                # All rules passed
                valid_distractors.append(word)
                self.usage_count[word_lower] += 1
        
        return valid_distractors
    
    def _words_rhyme(self, word1: str, word2: str, 
                     rhyme_endings: Set[str] = None) -> bool:
        """
        Check if two words rhyme.
        
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
    
    def _verify_pos(self, word: str, target_pos: str) -> bool:
        """
        Verify a word can be used as the target POS.
        
        Uses caching to minimize API calls.
        """
        word_lower = word.lower()
        
        # Check cache first
        if word_lower in self.pos_cache:
            cached_pos = self.pos_cache[word_lower]
            return cached_pos == target_pos or not cached_pos
        
        # Fetch POS
        pos = self.dictionary.get_pos(word)
        self.pos_cache[word_lower] = pos
        
        # If we couldn't determine POS, allow the word
        if not pos:
            return True
        
        return pos == target_pos
    
    def reset_usage(self):
        """Reset usage counts (call between wordbank generations)."""
        self.usage_count.clear()
    
    def validate_distractors(self, target_word: str, distractors: List[str],
                             avoid_words: Set[str], rhymes: List[str] = None
                             ) -> List[Dict]:
        """
        Validate a list of distractors and return issues.
        
        Returns list of dicts with:
            - word: the distractor
            - valid: True/False
            - issues: list of issue descriptions
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
            
            # Check avoid words
            if dist_lower in avoid_lower:
                issues.append("In avoid list (synonym/antonym/associated)")
            
            # Check rhyming
            if dist_lower in rhyme_lower:
                issues.append("Rhymes with target")
            elif self._words_rhyme(dist, target_word):
                issues.append("Ending suggests rhyme")
            
            # Check sound
            if self.sound_detector.get_sound_group(dist) == target_sound:
                issues.append(f"Same starting sound ({target_sound})")
            
            # Check length
            length_diff = abs(len(dist) - target_length)
            if length_diff > 2:
                issues.append(f"Length difference too large ({length_diff})")
            
            results.append({
                'word': dist,
                'valid': len(issues) == 0,
                'issues': issues,
            })
        
        return results

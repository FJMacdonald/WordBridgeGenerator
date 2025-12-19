"""
Sound group detection for phonetic exercises.

Detects the starting sound pattern of words for:
- Grouping words by initial sound
- Ensuring distractors don't start with the same sound
"""

from typing import Dict, List, Tuple


class SoundGroupDetector:
    """
    Detects starting sound groups for words.
    
    Handles complex sound patterns like:
    - Digraphs: th, sh, ch, ph, wh
    - Silent letters: kn, gn, wr
    - Consonant clusters: str, spr, scr, squ
    """
    
    # Sound patterns ordered by length (longer patterns first)
    # Format: (written pattern, phonetic representation)
    PATTERNS_EN = [
        # Three-letter patterns
        ("thr", "θr"),
        ("shr", "ʃr"),
        ("scr", "skr"),
        ("spr", "spr"),
        ("str", "str"),
        ("squ", "skw"),
        ("sch", "sk"),
        
        # Two-letter patterns
        ("th", "θ"),
        ("sh", "ʃ"),
        ("ch", "tʃ"),
        ("ph", "f"),
        ("wh", "w"),
        ("wr", "r"),
        ("kn", "n"),
        ("gn", "n"),
        ("qu", "kw"),
        ("ck", "k"),
        ("ng", "ŋ"),
        
        # Single letters map to themselves
    ]
    
    PATTERNS_DE = [
        # German patterns
        ("sch", "ʃ"),
        ("chr", "kr"),
        ("chs", "ks"),
        ("ch", "x"),
        ("ph", "f"),
        ("qu", "kv"),
        ("sp", "ʃp"),
        ("st", "ʃt"),
        ("th", "t"),
        ("pf", "pf"),
        ("kn", "kn"),
        ("gn", "gn"),
        
        # Umlauts
        ("ä", "ɛ"),
        ("ö", "ø"),
        ("ü", "y"),
    ]
    
    def __init__(self, language: str = "en"):
        """
        Initialize sound detector.
        
        Args:
            language: Language code ('en', 'de', etc.)
        """
        self.language = language
        self.patterns = self._get_patterns()
    
    def _get_patterns(self) -> List[Tuple[str, str]]:
        """Get sound patterns for current language."""
        if self.language == "de":
            return self.PATTERNS_DE
        return self.PATTERNS_EN
    
    def get_sound_group(self, word: str) -> str:
        """
        Get the starting sound group for a word.
        
        Args:
            word: Word to analyze
            
        Returns:
            Sound group string (e.g., 'sh', 'th', 'a')
        """
        if not word:
            return ""
        
        word_lower = word.lower().strip()
        
        # Check multi-character patterns first (sorted by length)
        for pattern, _ in sorted(self.patterns, key=lambda x: -len(x[0])):
            if word_lower.startswith(pattern):
                return pattern
        
        # Default to first character
        return word_lower[0] if word_lower else ""
    
    def same_sound(self, word1: str, word2: str) -> bool:
        """
        Check if two words start with the same sound.
        
        Args:
            word1: First word
            word2: Second word
            
        Returns:
            True if both words start with the same sound
        """
        return self.get_sound_group(word1) == self.get_sound_group(word2)
    
    def get_phonetic(self, word: str) -> str:
        """
        Get phonetic representation of starting sound.
        
        Args:
            word: Word to analyze
            
        Returns:
            IPA-like phonetic string
        """
        if not word:
            return ""
        
        word_lower = word.lower().strip()
        
        for pattern, phonetic in self.patterns:
            if word_lower.startswith(pattern):
                return phonetic
        
        return word_lower[0] if word_lower else ""
    
    def group_words_by_sound(self, words: List[str]) -> Dict[str, List[str]]:
        """
        Group a list of words by their starting sound.
        
        Args:
            words: List of words to group
            
        Returns:
            Dict mapping sound group to list of words
        """
        groups: Dict[str, List[str]] = {}
        
        for word in words:
            sound = self.get_sound_group(word)
            if sound not in groups:
                groups[sound] = []
            groups[sound].append(word)
        
        return groups

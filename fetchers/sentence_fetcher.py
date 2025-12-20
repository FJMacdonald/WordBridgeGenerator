"""
Sentence fetcher for example sentences.

Fetches from:
1. Dictionary examples (from definitions) - PRIMARY SOURCE
2. Tatoeba API (backup)

Sentence Requirements:
- Minimum 4 words
- Must contain the EXACT target word (not variations!)
- Proper capitalization and punctuation
- Be single sentences (not lists or fragments)

Goal: Return 2 sentences per word
- One shorter sentence (4-8 words ideal)
- One longer sentence (8+ words)

NO FALLBACKS OR HARDCODED VALUES - if no valid sentence is found,
return an empty list and mark the entry for review.
"""

import re
import time
import requests
from typing import List, Dict, Optional, Tuple

from ..config import URLS, API_DELAY, MIN_SENTENCE_WORDS
from ..utils.cache import cache_get, cache_set


class SentenceFetcher:
    """
    Fetches example sentences from dictionary sources.
    
    All sentences must:
    - Be at least MIN_SENTENCE_WORDS words long
    - Contain the EXACT target word (not a variation!)
    - Be properly formatted (capitalized, end with punctuation)
    - Be single sentences (not lists or fragments)
    
    Returns 2 sentences when possible:
    - One shorter (4-8 words)
    - One longer (8+ words)
    
    NO HARDCODED PHRASES - all data must come from external sources.
    """
    
    # Ideal sentence lengths for variety
    SHORT_SENTENCE_MAX = 8
    LONG_SENTENCE_MIN = 8
    
    def __init__(self):
        self.cache: Dict[str, List[str]] = {}
    
    def fetch_sentences(self, word: str, count: int = 2, 
                        dictionary_examples: List[str] = None) -> List[str]:
        """
        Fetch example sentences for a word.
        
        Goal: Return exactly 2 sentences when possible:
        - One shorter sentence (4-8 words)
        - One longer sentence (8+ words)
        
        Args:
            word: Target word (EXACT match required)
            count: Number of sentences to return (default 2)
            dictionary_examples: Optional list of examples from dictionary API
            
        Returns:
            List of validated sentences (may be empty if none found)
        """
        word_lower = word.lower().strip()
        
        # Check cache
        cache_key = f"sentences_v4_{word_lower}"
        cached = cache_get(cache_key)
        if cached:
            return self._select_varied_sentences(cached, word_lower, count)
        
        all_sentences = []
        
        # Source 1: Dictionary examples (if provided)
        if dictionary_examples:
            for example in dictionary_examples:
                if self._validate_sentence(example, word_lower):
                    formatted = self._format_sentence(example)
                    if formatted and formatted not in all_sentences:
                        all_sentences.append(formatted)
        
        # Source 2: Tatoeba API
        if len(all_sentences) < count * 3:  # Get more than needed for variety
            tatoeba_sentences = self._fetch_from_tatoeba(word_lower)
            for sentence in tatoeba_sentences:
                if self._validate_sentence(sentence, word_lower):
                    formatted = self._format_sentence(sentence)
                    if formatted and formatted not in all_sentences:
                        all_sentences.append(formatted)
        
        # Cache all found sentences
        cache_set(cache_key, all_sentences)
        
        # Select varied sentences (one short, one long)
        return self._select_varied_sentences(all_sentences, word_lower, count)
    
    def _select_varied_sentences(self, sentences: List[str], word: str, 
                                  count: int) -> List[str]:
        """
        Select a varied set of sentences (one short, one long when possible).
        
        Args:
            sentences: List of validated sentences
            word: Target word
            count: Number of sentences to return
            
        Returns:
            List of selected sentences with varied lengths
        """
        if not sentences:
            return []
        
        if len(sentences) == 1:
            return sentences
        
        # Categorize by length
        short_sentences = []
        long_sentences = []
        
        for sentence in sentences:
            word_count = len(sentence.split())
            if word_count <= self.SHORT_SENTENCE_MAX:
                short_sentences.append((word_count, sentence))
            if word_count >= self.LONG_SENTENCE_MIN:
                long_sentences.append((word_count, sentence))
        
        result = []
        
        # Try to get one short sentence (prefer 5-7 words - not too short)
        if short_sentences:
            # Sort by word count, prefer middle range (5-7 words)
            short_sentences.sort(key=lambda x: abs(x[0] - 6))
            result.append(short_sentences[0][1])
        
        # Try to get one long sentence (prefer 10-15 words - not too long)
        if long_sentences:
            # Sort by word count, prefer middle range (10-15 words)
            long_sentences.sort(key=lambda x: abs(x[0] - 12))
            for wc, sent in long_sentences:
                if sent not in result:
                    result.append(sent)
                    break
        
        # If we don't have enough variety, just add more sentences
        if len(result) < count:
            for sentence in sentences:
                if sentence not in result:
                    result.append(sentence)
                if len(result) >= count:
                    break
        
        return result[:count]
    
    def _fetch_from_tatoeba(self, word: str) -> List[str]:
        """Fetch sentences from Tatoeba API."""
        sentences = []
        
        try:
            params = {
                'from': 'eng',
                'query': word,
                'limit': 30,  # Get more for variety
            }
            
            resp = requests.get(URLS['tatoeba'], params=params, timeout=15)
            
            if resp.status_code != 200:
                return sentences
            
            data = resp.json()
            
            for result in data.get('results', []):
                text = result.get('text', '').strip()
                if text:
                    sentences.append(text)
            
        except Exception as e:
            pass
        
        return sentences
    
    def _validate_sentence(self, sentence: str, word: str) -> bool:
        """
        Validate that a sentence meets all requirements.
        
        Requirements:
        - At least MIN_SENTENCE_WORDS words
        - Contains the EXACT target word (not variations)
        - Properly formatted
        - Single sentence (not list or fragment)
        
        Args:
            sentence: Sentence to validate
            word: Target word (lowercase)
            
        Returns:
            True if sentence is valid
        """
        if not sentence:
            return False
        
        sentence = sentence.strip()
        
        # Check word count
        words = sentence.split()
        if len(words) < MIN_SENTENCE_WORDS:
            return False
        
        # Check for EXACT word match (not variations)
        # Use word boundaries to ensure exact match
        sentence_lower = sentence.lower()
        pattern = rf'\b{re.escape(word)}\b'
        if not re.search(pattern, sentence_lower):
            return False
        
        # Reject if contains a variation but not the exact word
        # For example, for "run", reject "running" sentences
        # This is already handled by the word boundary check above
        
        # Check it's a single sentence (not multiple sentences or list)
        # Allow one period at the end, but not multiple inside
        stripped = sentence.rstrip('.!?')
        if '.' in stripped:
            # Check for common abbreviations
            abbr_pattern = r'\b(Mr|Mrs|Ms|Dr|St|Jr|Sr|vs|etc|e\.g|i\.e|Prof|Inc|Ltd|Corp)\.'
            cleaned = re.sub(abbr_pattern, '', stripped, flags=re.IGNORECASE)
            if '.' in cleaned:
                # Still has periods - likely multiple sentences
                # But check if it's just one additional sentence marker
                if cleaned.count('.') > 1:
                    return False
        
        # Check for list-like structure
        if '\n' in sentence:
            return False
        if sentence.startswith('-') or sentence.startswith('•'):
            return False
        if sentence.startswith('1.') or sentence.startswith('2.'):
            return False
        
        # Reject sentences that are too long (likely compound)
        if len(words) > 25:
            return False
        
        return True
    
    def _format_sentence(self, sentence: str) -> str:
        """
        Format a sentence with proper capitalization and punctuation.
        
        Args:
            sentence: Raw sentence
            
        Returns:
            Formatted sentence
        """
        sentence = sentence.strip()
        
        if not sentence:
            return ''
        
        # Clean up extra whitespace
        sentence = re.sub(r'\s+', ' ', sentence)
        
        # Ensure first character is uppercase
        if sentence[0].islower():
            sentence = sentence[0].upper() + sentence[1:]
        
        # Ensure ends with punctuation
        if sentence[-1] not in '.!?':
            sentence += '.'
        
        # Final validation
        if not self._is_properly_formatted(sentence):
            return ''
        
        return sentence
    
    def _is_properly_formatted(self, sentence: str) -> bool:
        """
        Check if a sentence is properly formatted.
        
        Args:
            sentence: Sentence to check
            
        Returns:
            True if properly formatted
        """
        if not sentence:
            return False
        
        # Must start with uppercase
        if not sentence[0].isupper():
            return False
        
        # Must end with punctuation
        if sentence[-1] not in '.!?':
            return False
        
        # Must have reasonable length
        if len(sentence) < 10:
            return False
        
        return True
    
    def fetch_dictionary_examples(self, word: str, 
                                   definition_data: Dict) -> List[str]:
        """
        Extract example sentences from dictionary data.
        
        This method is called by the word generator to extract examples
        from the dictionary API response.
        
        Args:
            word: Target word
            definition_data: Dictionary response data
            
        Returns:
            List of validated example sentences
        """
        word_lower = word.lower().strip()
        examples = []
        
        if not definition_data:
            return examples
        
        # Extract single example
        example = definition_data.get('example', '')
        if example and self._validate_sentence(example, word_lower):
            formatted = self._format_sentence(example)
            if formatted:
                examples.append(formatted)
        
        # Extract all examples if available
        all_examples = definition_data.get('examples', [])
        for ex in all_examples:
            if ex and self._validate_sentence(ex, word_lower):
                formatted = self._format_sentence(ex)
                if formatted and formatted not in examples:
                    examples.append(formatted)
        
        return examples

"""
Sentence fetcher for example sentences.

Fetches from:
1. Dictionary examples (from definitions) - PRIMARY SOURCE
2. Tatoeba API (backup)

Sentences must:
- Be at least MIN_SENTENCE_WORDS words long
- Contain the EXACT target word (not variations!)
- Have proper capitalization and punctuation
- Be single sentences (not lists or fragments)

NO FALLBACKS OR HARDCODED VALUES - if no valid sentence is found,
return an empty list and mark the entry for review.
"""

import re
import time
import requests
from typing import List, Dict, Optional

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
    
    NO HARDCODED PHRASES - all data must come from external sources.
    """
    
    def __init__(self):
        self.cache: Dict[str, List[str]] = {}
    
    def fetch_sentences(self, word: str, count: int = 2, 
                        dictionary_examples: List[str] = None) -> List[str]:
        """
        Fetch example sentences for a word.
        
        Args:
            word: Target word (EXACT match required)
            count: Number of sentences to return
            dictionary_examples: Optional list of examples from dictionary API
            
        Returns:
            List of validated sentences (may be empty if none found)
        """
        word_lower = word.lower().strip()
        
        # Check cache
        cache_key = f"sentences_v3_{word_lower}"
        cached = cache_get(cache_key)
        if cached:
            return self._filter_sentences(cached, word_lower, count)
        
        sentences = []
        
        # Source 1: Dictionary examples (if provided)
        if dictionary_examples:
            for example in dictionary_examples:
                if self._validate_sentence(example, word_lower):
                    sentences.append(example)
        
        # Source 2: Tatoeba API
        if len(sentences) < count * 2:
            tatoeba_sentences = self._fetch_from_tatoeba(word_lower)
            for sentence in tatoeba_sentences:
                if self._validate_sentence(sentence, word_lower):
                    if sentence not in sentences:
                        sentences.append(sentence)
        
        # Remove duplicates while preserving order
        sentences = list(dict.fromkeys(sentences))
        
        # Cache all found sentences
        cache_set(cache_key, sentences)
        
        # Filter and return
        return self._filter_sentences(sentences, word_lower, count)
    
    def _fetch_from_tatoeba(self, word: str) -> List[str]:
        """Fetch sentences from Tatoeba API."""
        sentences = []
        
        try:
            params = {
                'from': 'eng',
                'query': word,
                'limit': 20,
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
        
        # Check it's a single sentence (not multiple sentences or list)
        # Allow one period at the end, but not multiple inside
        stripped = sentence.rstrip('.!?')
        if '.' in stripped and not any(abbr in stripped.lower() for abbr in 
                                        ['mr.', 'mrs.', 'dr.', 'st.', 'e.g.', 'i.e.']):
            # Might be multiple sentences
            if stripped.count('.') > 1:
                return False
        
        # Check for list-like structure
        if '\n' in sentence:
            return False
        if sentence.startswith('-') or sentence.startswith('•'):
            return False
        
        return True
    
    def _filter_sentences(self, sentences: List[str], word: str, 
                          count: int) -> List[str]:
        """
        Filter and format sentences to meet quality requirements.
        
        Args:
            sentences: List of candidate sentences
            word: Target word (lowercase)
            count: Maximum number to return
            
        Returns:
            List of validated and formatted sentences
        """
        valid = []
        
        for sentence in sentences:
            if len(valid) >= count:
                break
            
            # Skip if doesn't validate
            if not self._validate_sentence(sentence, word):
                continue
            
            # Format the sentence
            sentence = self._format_sentence(sentence)
            
            # Final check that it's properly formatted
            if sentence and self._is_properly_formatted(sentence):
                valid.append(sentence)
        
        return valid
    
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
        
        # Ensure first character is uppercase
        if sentence[0].islower():
            sentence = sentence[0].upper() + sentence[1:]
        
        # Ensure ends with punctuation
        if sentence[-1] not in '.!?':
            sentence += '.'
        
        # Clean up extra whitespace
        sentence = re.sub(r'\s+', ' ', sentence)
        
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
        
        # Extract example from the definition data
        if definition_data:
            example = definition_data.get('example', '')
            if example and self._validate_sentence(example, word_lower):
                examples.append(example)
        
        return examples

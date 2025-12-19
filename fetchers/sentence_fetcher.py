"""
Sentence fetcher for example sentences and phrases/idioms.

Fetches from:
1. Tatoeba API (primary for sentences)
2. Dictionary examples (from definitions)
3. Common phrases database
"""

import re
import time
import requests
from typing import List, Dict, Optional

from ..config import URLS, API_DELAY, MIN_SENTENCE_WORDS
from ..utils.cache import cache_get, cache_set


class SentenceFetcher:
    """
    Fetches example sentences and phrases from multiple sources.
    
    All sentences must:
    - Be at least MIN_SENTENCE_WORDS words long
    - Contain the target word (or a variation)
    - Be properly formatted (capitalized, end with punctuation)
    - Be single sentences (not lists or fragments)
    """
    
    # Common phrases and idioms database
    # These are looked up by word
    COMMON_PHRASES = {
        'apple': ['apple of my eye', 'an apple a day keeps the doctor away', 'bad apple'],
        'ball': ['have a ball', 'ball is in your court', 'drop the ball', 'on the ball'],
        'bed': ['make your bed', 'get out of bed on the wrong side', 'bed of roses'],
        'bird': ['early bird catches the worm', 'birds of a feather', 'free as a bird'],
        'book': ['by the book', 'open book', 'book it', 'in my book'],
        'bread': ['bread and butter', 'best thing since sliced bread', 'break bread'],
        'cake': ['piece of cake', 'icing on the cake', 'have your cake and eat it too'],
        'cat': ['let the cat out of the bag', 'cat got your tongue', 'raining cats and dogs'],
        'cloud': ['on cloud nine', 'every cloud has a silver lining', 'head in the clouds'],
        'day': ['day in day out', 'call it a day', 'save the day', 'day and night'],
        'dog': ['dog days', 'let sleeping dogs lie', 'every dog has its day'],
        'door': ['behind closed doors', 'foot in the door', 'open doors'],
        'eye': ['keep an eye on', 'see eye to eye', 'eye for an eye', 'in the blink of an eye'],
        'face': ['face the music', 'save face', 'face to face', 'straight face'],
        'fire': ['play with fire', 'under fire', 'fire away', 'add fuel to the fire'],
        'fish': ['big fish', 'fish out of water', 'plenty of fish in the sea'],
        'foot': ['put your foot down', 'get cold feet', 'foot the bill'],
        'hand': ['hand in hand', 'hands down', 'give a hand', 'out of hand'],
        'head': ['head over heels', 'heads up', 'head start', 'keep your head'],
        'heart': ['heart of gold', 'by heart', 'change of heart', 'heart to heart'],
        'home': ['home sweet home', 'make yourself at home', 'home run', 'hit home'],
        'horse': ['hold your horses', 'straight from the horse\'s mouth', 'dark horse'],
        'ice': ['break the ice', 'on thin ice', 'ice breaker'],
        'leaf': ['turn over a new leaf', 'take a leaf out of someone\'s book'],
        'light': ['light at the end of the tunnel', 'see the light', 'light as a feather'],
        'moon': ['over the moon', 'once in a blue moon', 'shoot for the moon'],
        'nail': ['hit the nail on the head', 'nail it', 'tough as nails'],
        'rain': ['rain or shine', 'rain check', 'save for a rainy day'],
        'road': ['hit the road', 'down the road', 'end of the road'],
        'rock': ['rock solid', 'between a rock and a hard place', 'rock the boat'],
        'ship': ['ship shape', 'when my ship comes in', 'tight ship'],
        'star': ['reach for the stars', 'star quality', 'see stars'],
        'stone': ['leave no stone unturned', 'stone cold', 'set in stone'],
        'sun': ['place in the sun', 'under the sun', 'sunny side up'],
        'table': ['on the table', 'under the table', 'turn the tables'],
        'time': ['time flies', 'time is money', 'from time to time', 'in no time'],
        'tree': ['barking up the wrong tree', 'money doesn\'t grow on trees'],
        'water': ['water under the bridge', 'in hot water', 'test the waters'],
        'wind': ['wind down', 'second wind', 'throw caution to the wind'],
        'word': ['word of mouth', 'in other words', 'have the last word'],
    }
    
    def __init__(self):
        self.cache: Dict[str, List[str]] = {}
    
    def fetch_sentences(self, word: str, count: int = 2) -> List[str]:
        """
        Fetch example sentences for a word.
        
        Args:
            word: Target word
            count: Number of sentences to return
            
        Returns:
            List of validated sentences (may be empty if none found)
        """
        word_lower = word.lower().strip()
        
        # Check cache
        cache_key = f"sentences_v2_{word_lower}"
        cached = cache_get(cache_key)
        if cached:
            return self._filter_sentences(cached, word_lower, count)
        
        sentences = []
        
        # Try Tatoeba first
        tatoeba_sentences = self._fetch_from_tatoeba(word_lower)
        sentences.extend(tatoeba_sentences)
        
        # Try sentence.dict.cn if needed
        if len(sentences) < count * 2:
            time.sleep(API_DELAY)
            dict_sentences = self._fetch_from_sentence_dict(word_lower)
            sentences.extend(dict_sentences)
        
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
    
    def _fetch_from_sentence_dict(self, word: str) -> List[str]:
        """Fetch sentences from sentence.dict.cn using regex parsing."""
        sentences = []
        
        try:
            url = f"{URLS['sentence_dict']}/{word}"
            resp = requests.get(url, timeout=15)
            
            if resp.status_code != 200:
                return sentences
            
            # Parse HTML using regex to extract sentences
            # Look for common patterns in sentence example sites
            html = resp.text
            
            # Try to find sentence patterns
            patterns = [
                r'<p[^>]*class="[^"]*(?:sentence|example|eg)[^"]*"[^>]*>([^<]+)</p>',
                r'<span[^>]*class="[^"]*(?:sentence|example|eg)[^"]*"[^>]*>([^<]+)</span>',
                r'<div[^>]*class="[^"]*(?:sentence|example|eg)[^"]*"[^>]*>([^<]+)</div>',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    text = re.sub(r'\s+', ' ', match).strip()
                    if text and len(text) > 10:
                        sentences.append(text)
            
        except Exception as e:
            pass
        
        return sentences
    
    def _filter_sentences(self, sentences: List[str], word: str, 
                          count: int) -> List[str]:
        """
        Filter sentences to meet quality requirements.
        
        Requirements:
        - At least MIN_SENTENCE_WORDS words
        - Contains the target word
        - Properly formatted
        - Single sentence (no multi-word results)
        """
        valid = []
        word_lower = word.lower()
        
        # Generate word variations for matching
        variations = self._get_word_variations(word_lower)
        
        for sentence in sentences:
            if len(valid) >= count:
                break
            
            # Clean up the sentence
            sentence = sentence.strip()
            
            # Check word count
            words = sentence.split()
            if len(words) < MIN_SENTENCE_WORDS:
                continue
            
            # Check if it contains the word or a variation
            sentence_lower = sentence.lower()
            found = False
            for var in variations:
                if re.search(rf'\b{re.escape(var)}\b', sentence_lower):
                    found = True
                    break
            
            if not found:
                continue
            
            # Check formatting
            if not sentence[0].isupper():
                sentence = sentence[0].upper() + sentence[1:]
            
            if sentence[-1] not in '.!?':
                sentence += '.'
            
            # Check it's a single sentence (not a list or multiple sentences)
            if sentence.count('.') > 2 or '\n' in sentence:
                continue
            
            valid.append(sentence)
        
        return valid
    
    def _get_word_variations(self, word: str) -> List[str]:
        """Get word variations for matching in sentences."""
        variations = [word]
        
        # Add common variations
        if word.endswith('s'):
            variations.append(word[:-1])
        else:
            variations.append(word + 's')
            variations.append(word + 'es')
        
        if word.endswith('e'):
            variations.append(word + 'd')
            variations.append(word[:-1] + 'ing')
        else:
            variations.append(word + 'ed')
            variations.append(word + 'ing')
        
        if word.endswith('y'):
            variations.append(word[:-1] + 'ies')
            variations.append(word[:-1] + 'ied')
        
        return variations
    
    def fetch_phrases(self, word: str) -> List[str]:
        """
        Fetch common phrases and idioms containing the word.
        
        Args:
            word: Target word
            
        Returns:
            List of phrases/idioms
        """
        word_lower = word.lower().strip()
        
        # Check our database first
        phrases = self.COMMON_PHRASES.get(word_lower, [])
        
        # Also check variations
        if not phrases:
            # Try without 's' or with 's'
            if word_lower.endswith('s'):
                phrases = self.COMMON_PHRASES.get(word_lower[:-1], [])
            else:
                phrases = self.COMMON_PHRASES.get(word_lower + 's', [])
        
        return phrases[:5]

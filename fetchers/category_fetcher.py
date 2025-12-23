"""
Category fetcher using Datamuse API.

Uses Datamuse rel_gen (generalization) to assign categories to words.
For example, "dog" -> "animal", "apple" -> "fruit"

This provides semantic categories based on hypernym relationships.
"""

import time
import requests
from typing import Optional, List, Dict

from ..config import URLS, API_DELAY
from ..utils.cache import cache_get, cache_set


class CategoryFetcher:
    """
    Fetches semantic categories for words using Datamuse API.
    
    Uses rel_gen (generalization/hypernym) to find the category.
    For nouns, this gives the "type of" relationship:
    - dog -> animal
    - apple -> fruit
    - car -> vehicle
    """
    
    # Known category mappings for common words
    # These override API results for consistency
    KNOWN_CATEGORIES = {
        # Animals
        'dog': 'animal', 'cat': 'animal', 'bird': 'animal', 'fish': 'animal',
        'horse': 'animal', 'cow': 'animal', 'pig': 'animal', 'sheep': 'animal',
        'lion': 'animal', 'tiger': 'animal', 'bear': 'animal', 'elephant': 'animal',
        'mouse': 'animal', 'rabbit': 'animal', 'duck': 'animal', 'chicken': 'animal',
        
        # Food
        'apple': 'food', 'banana': 'food', 'orange': 'food', 'bread': 'food',
        'cheese': 'food', 'meat': 'food', 'rice': 'food', 'pasta': 'food',
        'vegetable': 'food', 'fruit': 'food', 'cake': 'food', 'pizza': 'food',
        
        # Vehicles
        'car': 'vehicle', 'bus': 'vehicle', 'train': 'vehicle', 'plane': 'vehicle',
        'boat': 'vehicle', 'ship': 'vehicle', 'bicycle': 'vehicle', 'motorcycle': 'vehicle',
        'truck': 'vehicle', 'taxi': 'vehicle', 'helicopter': 'vehicle',
        
        # Body parts
        'hand': 'body part', 'foot': 'body part', 'head': 'body part', 'eye': 'body part',
        'ear': 'body part', 'nose': 'body part', 'mouth': 'body part', 'arm': 'body part',
        'leg': 'body part', 'finger': 'body part', 'toe': 'body part', 'face': 'body part',
        
        # Furniture
        'chair': 'furniture', 'table': 'furniture', 'bed': 'furniture', 'desk': 'furniture',
        'sofa': 'furniture', 'couch': 'furniture', 'shelf': 'furniture', 'cabinet': 'furniture',
        
        # Clothing
        'shirt': 'clothing', 'pants': 'clothing', 'dress': 'clothing', 'shoe': 'clothing',
        'hat': 'clothing', 'coat': 'clothing', 'jacket': 'clothing', 'sock': 'clothing',
        
        # Buildings/Places
        'house': 'building', 'home': 'building', 'school': 'building', 'hospital': 'building',
        'store': 'building', 'shop': 'building', 'church': 'building', 'office': 'building',
        
        # Nature
        'tree': 'plant', 'flower': 'plant', 'grass': 'plant', 'leaf': 'plant',
        'sun': 'celestial body', 'moon': 'celestial body', 'star': 'celestial body',
        'rain': 'weather', 'snow': 'weather', 'wind': 'weather', 'cloud': 'weather',
        'river': 'water body', 'lake': 'water body', 'ocean': 'water body', 'sea': 'water body',
        'mountain': 'landform', 'hill': 'landform', 'valley': 'landform',
        
        # Time
        'day': 'time', 'night': 'time', 'morning': 'time', 'evening': 'time',
        'week': 'time', 'month': 'time', 'year': 'time', 'hour': 'time', 'minute': 'time',
        
        # Tools
        'hammer': 'tool', 'knife': 'tool', 'scissors': 'tool', 'pen': 'tool',
        'pencil': 'tool', 'brush': 'tool', 'key': 'tool',
        
        # Electronics
        'phone': 'device', 'computer': 'device', 'television': 'device', 'radio': 'device',
        'camera': 'device', 'clock': 'device', 'watch': 'device',
        
        # People/Occupations
        'doctor': 'person', 'teacher': 'person', 'student': 'person', 'child': 'person',
        'baby': 'person', 'man': 'person', 'woman': 'person', 'boy': 'person', 'girl': 'person',
        
        # Sports/Games
        'ball': 'sports equipment', 'game': 'activity', 'sport': 'activity',
    }
    
    # Preferred categories (more specific is better)
    CATEGORY_PRIORITY = [
        'animal', 'food', 'vehicle', 'body part', 'furniture', 'clothing',
        'building', 'plant', 'tool', 'device', 'person', 'activity',
        'weather', 'celestial body', 'water body', 'landform', 'time',
    ]
    
    def __init__(self):
        self.cache: Dict[str, str] = {}
    
    def fetch_category(self, word: str, pos: str = 'noun') -> str:
        """
        Fetch semantic category for a word.
        
        Args:
            word: The word to categorize
            pos: Part of speech (category only meaningful for nouns)
            
        Returns:
            Category string, or empty string if not found
        """
        # Categories are only meaningful for nouns
        if pos != 'noun':
            return ''
        
        word_lower = word.lower().strip()
        
        # Check known categories first
        if word_lower in self.KNOWN_CATEGORIES:
            return self.KNOWN_CATEGORIES[word_lower]
        
        # Check cache
        cache_key = f"category_v1_{word_lower}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        
        # Fetch from Datamuse
        category = self._fetch_from_datamuse(word_lower)
        
        # Cache result
        cache_set(cache_key, category)
        
        return category
    
    def _fetch_from_datamuse(self, word: str) -> str:
        """
        Fetch category from Datamuse using rel_gen (generalization).
        
        rel_gen returns hypernyms (more general terms).
        """
        try:
            url = f"{URLS['datamuse']}?rel_gen={word}&max=5"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return ''
            
            data = resp.json()
            
            if not data:
                return ''
            
            # Get the best category from results
            # Prefer results that match our known priority categories
            for item in data:
                candidate = item.get('word', '').lower()
                
                # Check if this is a known good category
                if candidate in self.CATEGORY_PRIORITY:
                    return candidate
                
                # Check if it's in our known categories values
                if candidate in set(self.KNOWN_CATEGORIES.values()):
                    return candidate
            
            # If no preferred category found, use the first result
            # (highest score from Datamuse)
            first_result = data[0].get('word', '')
            
            # Clean up the category
            if first_result:
                # Simplify compound categories
                first_result = first_result.split(',')[0].strip()
                return first_result
            
            return ''
            
        except Exception as e:
            return ''
    
    def get_category_with_fallback(self, word: str, emoji_category: str = '', 
                                    pos: str = 'noun') -> str:
        """
        Get category with emoji category as fallback.
        
        Priority:
        1. Datamuse rel_gen result
        2. Emoji category from BehrouzSohrabi/Emoji
        3. Empty string
        
        Args:
            word: The word to categorize
            emoji_category: Category from emoji fetcher (fallback)
            pos: Part of speech
            
        Returns:
            Best available category
        """
        if pos != 'noun':
            return ''
        
        # Try Datamuse first
        datamuse_category = self.fetch_category(word, pos)
        if datamuse_category:
            return datamuse_category
        
        # Fall back to emoji category
        if emoji_category:
            # Normalize emoji category
            normalized = emoji_category.lower()
            
            # Map emoji categories to our preferred categories
            emoji_category_map = {
                'animals & nature': 'animal',
                'food & drink': 'food',
                'travel & places': 'place',
                'activities': 'activity',
                'objects': 'object',
                'symbols': 'symbol',
                'people & body': 'person',
            }
            
            return emoji_category_map.get(normalized, normalized)
        
        return ''

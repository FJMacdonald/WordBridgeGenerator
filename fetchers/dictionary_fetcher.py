"""
Dictionary fetcher for definitions and parts of speech.

Fetches from multiple sources with priority:
1. Wordnik API (preferred - has frequency/commonality data)
2. Free Dictionary API (fallback)
3. dwyl/english-words (for word validation)

Key features:
- Prioritizes COMMON definitions over technical/rare ones
- Filters out archaic, obsolete, technical definitions
- Uses word frequency to determine most likely POS
"""

import re
import time
import requests
from typing import Dict, List, Set, Optional, Tuple

from ..config import URLS, API_DELAY, WORDNIK_API_KEY, EXCLUDED_WORDS
from ..utils.cache import cache_get, cache_set


class DictionaryFetcher:
    """
    Fetches word definitions from multiple dictionary sources.
    Prioritizes common, everyday definitions over technical/rare ones.
    """
    
    # Parts of speech we accept for wordbank
    VALID_POS = {'noun', 'verb', 'adjective', 'adverb'}
    
    # POS that should be filtered out
    EXCLUDED_POS = {'preposition', 'conjunction', 'pronoun', 'interjection', 
                    'determiner', 'article', 'particle', 'abbreviation',
                    'affix', 'prefix', 'suffix'}
    
    # Definition labels that indicate uncommon/technical usage
    # These definitions should be deprioritized or skipped
    UNCOMMON_LABELS = {
        'archaic', 'obsolete', 'rare', 'dated', 'historical',
        'technical', 'computing', 'programming', 'mathematics',
        'logic', 'philosophy', 'law', 'legal', 'medicine', 'medical',
        'chemistry', 'physics', 'biology', 'botany', 'zoology',
        'anatomy', 'linguistics', 'grammar', 'rhetoric',
        'dialectal', 'regional', 'slang', 'vulgar', 'offensive',
        'informal', 'colloquial', 'british', 'scottish', 'irish',
        'australian', 'nautical', 'military', 'heraldry',
        'baseball', 'cricket', 'golf', 'tennis', 'sports',
        'music', 'theatre', 'theater', 'printing', 'typography',
    }
    
    # Words in definitions that suggest technical/uncommon usage
    TECHNICAL_DEFINITION_WORDS = {
        'unary', 'binary', 'operator', 'operand', 'boolean',
        'syntax', 'semantics', 'morpheme', 'phoneme', 'lexeme',
        'algorithm', 'function', 'variable', 'parameter',
        'theorem', 'axiom', 'postulate', 'corollary',
        'genus', 'species', 'phylum', 'taxonomy',
        'plaintiff', 'defendant', 'tort', 'statute',
        'enzyme', 'protein', 'molecule', 'compound',
    }
    
    # POS frequency - most common usage patterns
    # Used when multiple POS are possible to pick the most likely one
    COMMON_POS_PATTERNS = {
        # Words that are primarily adjectives (not nouns)
        'new': 'adjective',
        'old': 'adjective', 
        'big': 'adjective',
        'small': 'adjective',
        'good': 'adjective',
        'bad': 'adjective',
        'free': 'adjective',
        'full': 'adjective',
        'empty': 'adjective',
        'open': 'adjective',
        'closed': 'adjective',
        'hot': 'adjective',
        'cold': 'adjective',
        'fast': 'adjective',
        'slow': 'adjective',
        'hard': 'adjective',
        'soft': 'adjective',
        'high': 'adjective',
        'low': 'adjective',
        'long': 'adjective',
        'short': 'adjective',
        'wide': 'adjective',
        'narrow': 'adjective',
        'deep': 'adjective',
        'shallow': 'adjective',
        'heavy': 'adjective',
        'light': 'adjective',
        'dark': 'adjective',
        'bright': 'adjective',
        'clean': 'adjective',
        'dirty': 'adjective',
        'wet': 'adjective',
        'dry': 'adjective',
        'sick': 'adjective',
        'healthy': 'adjective',
        'happy': 'adjective',
        'sad': 'adjective',
        'angry': 'adjective',
        'calm': 'adjective',
        'quiet': 'adjective',
        'loud': 'adjective',
        'rich': 'adjective',
        'poor': 'adjective',
        'young': 'adjective',
        'safe': 'adjective',
        'dangerous': 'adjective',
        'easy': 'adjective',
        'difficult': 'adjective',
        'simple': 'adjective',
        'complex': 'adjective',
        'real': 'adjective',
        'fake': 'adjective',
        'true': 'adjective',
        'false': 'adjective',
        'right': 'adjective',
        'wrong': 'adjective',
        'clear': 'adjective',
        'sure': 'adjective',
        'ready': 'adjective',
        'busy': 'adjective',
        'tired': 'adjective',
        'hungry': 'adjective',
        'thirsty': 'adjective',
        'alive': 'adjective',
        'dead': 'adjective',
        'awake': 'adjective',
        'asleep': 'adjective',
        
        # Words that are primarily adverbs (not adjectives/nouns)
        'not': 'adverb',
        'never': 'adverb',
        'always': 'adverb',
        'often': 'adverb',
        'sometimes': 'adverb',
        'usually': 'adverb',
        'rarely': 'adverb',
        'seldom': 'adverb',
        
        # Common nouns that should stay as nouns
        'home': 'noun',
        'house': 'noun',
        'page': 'noun',
        'site': 'noun',
        'time': 'noun',
        'day': 'noun',
        'year': 'noun',
        'world': 'noun',
        'life': 'noun',
        'hand': 'noun',
        'part': 'noun',
        'place': 'noun',
        'case': 'noun',
        'week': 'noun',
        'point': 'noun',
        'fact': 'noun',
        'group': 'noun',
        'number': 'noun',
        'night': 'noun',
        'room': 'noun',
        'water': 'noun',
        'money': 'noun',
        'story': 'noun',
        'eye': 'noun',
        'head': 'noun',
        'side': 'noun',
        'face': 'noun',
        'door': 'noun',
        'car': 'noun',
        'city': 'noun',
        'name': 'noun',
        'team': 'noun',
        'idea': 'noun',
        'body': 'noun',
        'back': 'noun',
        'word': 'noun',
        'book': 'noun',
        'food': 'noun',
        'fire': 'noun',
        'tree': 'noun',
        'bird': 'noun',
        'fish': 'noun',
        'dog': 'noun',
        'cat': 'noun',
        'ball': 'noun',
        'table': 'noun',
        'chair': 'noun',
        'bed': 'noun',
        'phone': 'noun',
        'car': 'noun',
        'bus': 'noun',
        'boat': 'noun',
        'train': 'noun',
        'plane': 'noun',
        'road': 'noun',
        'street': 'noun',
        'river': 'noun',
        'mountain': 'noun',
        'sun': 'noun',
        'moon': 'noun',
        'star': 'noun',
        'rain': 'noun',
        'snow': 'noun',
        'wind': 'noun',
        'cloud': 'noun',
        'flower': 'noun',
        'grass': 'noun',
        
        # Words that are primarily verbs
        'run': 'verb',
        'walk': 'verb',
        'talk': 'verb',
        'eat': 'verb',
        'drink': 'verb',
        'sleep': 'verb',
        'work': 'verb',
        'play': 'verb',
        'read': 'verb',
        'write': 'verb',
        'watch': 'verb',
        'listen': 'verb',
        'search': 'verb',
        'find': 'verb',
        'look': 'verb',
        'help': 'verb',
        'start': 'verb',
        'stop': 'verb',
        'begin': 'verb',
        'end': 'verb',
        'open': 'verb',  # Can be both adj and verb
        'close': 'verb',
        'buy': 'verb',
        'sell': 'verb',
        'give': 'verb',
        'send': 'verb',
        'call': 'verb',
        'ask': 'verb',
        'answer': 'verb',
        'try': 'verb',
        'learn': 'verb',
        'teach': 'verb',
        'show': 'verb',
        'tell': 'verb',
        'move': 'verb',
        'change': 'verb',
        'grow': 'verb',
        'live': 'verb',
        'love': 'verb',
        'hate': 'verb',
        'like': 'verb',
        'want': 'verb',
        'need': 'verb',
        'feel': 'verb',
        'think': 'verb',
        'believe': 'verb',
        'remember': 'verb',
        'forget': 'verb',
        'understand': 'verb',
    }
    
    def __init__(self):
        self.word_list: Set[str] = set()
        self._word_list_fetched = False
        self.definition_cache: Dict[str, Dict] = {}
    
    def fetch_word_list(self) -> bool:
        """Fetch the English word list for validation."""
        if self._word_list_fetched:
            return True
        
        # Check cache
        cached = cache_get("english_word_list_v3")
        if cached:
            self.word_list = set(cached)
            self._word_list_fetched = True
            return True
        
        print("📚 Fetching English word list...")
        
        try:
            resp = requests.get(URLS['english_words'], timeout=60)
            resp.raise_for_status()
            data = resp.json()
            
            # Filter to reasonable words
            self.word_list = {
                word.lower() for word in data.keys()
                if 3 <= len(word) <= 15 and word.isalpha()
            }
            
            # Cache
            cache_set("english_word_list_v3", list(self.word_list))
            
            print(f"   ✓ Loaded {len(self.word_list)} words")
            self._word_list_fetched = True
            return True
            
        except Exception as e:
            print(f"   ⚠ Failed to fetch word list: {e}")
            return False
    
    def is_valid_word(self, word: str) -> bool:
        """Check if a word is in the dictionary."""
        if not self._word_list_fetched:
            self.fetch_word_list()
        return word.lower() in self.word_list
    
    def fetch_definition(self, word: str) -> Optional[Dict]:
        """
        Fetch definition data for a word.
        Prioritizes Wordnik, falls back to Free Dictionary.
        Filters for common, everyday definitions.
        
        Returns dict with:
            - word: the word
            - definition: main definition (common usage)
            - pos: part of speech (most common)
            - synonyms: list of synonyms
            - antonyms: list of antonyms
            - example: example sentence (if available)
            - all_pos: list of all POS this word can be
            
        Returns None if word should be excluded.
        """
        word_lower = word.lower().strip()
        
        # Check if word is in EXCLUDED_WORDS
        if word_lower in EXCLUDED_WORDS:
            return None
        
        # Check cache
        cache_key = f"definition_v3_{word_lower}"
        cached = cache_get(cache_key)
        if cached:
            if cached.get('excluded'):
                return None
            return cached if cached.get('definition') else None
        
        result = {
            'word': word,
            'definition': '',
            'pos': '',
            'synonyms': [],
            'antonyms': [],
            'example': '',
            'all_pos': [],
        }
        
        # Check if we have a known common POS for this word
        expected_pos = self.COMMON_POS_PATTERNS.get(word_lower)
        
        # Try Wordnik first (better quality, has frequency data)
        if WORDNIK_API_KEY:
            wordnik_result = self._fetch_from_wordnik(word_lower, expected_pos)
            if wordnik_result and wordnik_result.get('definition'):
                result.update(wordnik_result)
        
        # Fall back to Free Dictionary if Wordnik didn't work
        if not result['definition']:
            time.sleep(API_DELAY)
            free_dict_result = self._fetch_from_free_dictionary(word_lower, expected_pos)
            if free_dict_result:
                # Merge results
                if not result['definition']:
                    result['definition'] = free_dict_result.get('definition', '')
                if not result['pos']:
                    result['pos'] = free_dict_result.get('pos', '')
                result['synonyms'] = list(set(
                    result['synonyms'] + free_dict_result.get('synonyms', [])
                ))[:5]
                result['antonyms'] = list(set(
                    result['antonyms'] + free_dict_result.get('antonyms', [])
                ))[:5]
                if not result['example']:
                    result['example'] = free_dict_result.get('example', '')
                result['all_pos'] = list(set(
                    result['all_pos'] + free_dict_result.get('all_pos', [])
                ))
        
        # Override POS if we have a known common pattern
        if expected_pos and expected_pos in result.get('all_pos', []):
            result['pos'] = expected_pos
        
        # Check if POS is excluded
        if result['pos'] in self.EXCLUDED_POS:
            cache_set(cache_key, {'excluded': True, 'pos': result['pos']})
            return None
        
        # Validate the definition is good
        if result['definition']:
            if self._is_bad_definition(result['definition'], word_lower):
                # Try to get a better definition
                result['definition'] = ''
        
        # Cache the result
        cache_set(cache_key, result)
        
        return result if result['definition'] else None
    
    def _is_bad_definition(self, definition: str, word: str) -> bool:
        """
        Check if a definition is low quality.
        Returns True if definition should be rejected.
        """
        def_lower = definition.lower()
        
        # Reject circular definitions ("Things that are X" for word X)
        if f"things that are {word}" in def_lower:
            return True
        if f"the quality of being {word}" in def_lower:
            return True
        if f"the state of being {word}" in def_lower:
            return True
        if definition.strip().lower() == word:
            return True
        
        # Reject very short definitions
        if len(definition) < 10:
            return True
        
        # Reject definitions with technical words
        for tech_word in self.TECHNICAL_DEFINITION_WORDS:
            if tech_word in def_lower:
                return True
        
        return False
    
    def _is_common_definition(self, definition: str, labels: List[str]) -> bool:
        """
        Check if a definition represents common/everyday usage.
        """
        # Check labels for uncommon markers
        for label in labels:
            label_lower = label.lower()
            for uncommon in self.UNCOMMON_LABELS:
                if uncommon in label_lower:
                    return False
        
        def_lower = definition.lower()
        
        # Check for uncommon markers in the definition itself
        uncommon_phrases = [
            'in baseball', 'in cricket', 'in golf', 'in tennis',
            'in computing', 'in programming', 'in mathematics',
            'in logic', 'in philosophy', 'in law', 'in medicine',
            'archaic', 'obsolete', 'rare', 'dated', 'historical',
            'technical term', 'legal term', 'medical term',
            'chiefly british', 'chiefly scottish',
        ]
        
        for phrase in uncommon_phrases:
            if phrase in def_lower:
                return False
        
        return True
    
    def _fetch_from_wordnik(self, word: str, expected_pos: str = None) -> Optional[Dict]:
        """
        Fetch from Wordnik API.
        Wordnik provides better definition quality and frequency data.
        """
        if not WORDNIK_API_KEY:
            return None
        
        result = {
            'definition': '',
            'pos': '',
            'synonyms': [],
            'antonyms': [],
            'example': '',
            'all_pos': [],
        }
        
        try:
            # Get definitions with frequency info
            url = f"{URLS['wordnik']}/{word}/definitions"
            params = {
                'limit': 10,
                'includeRelated': 'false',
                'useCanonical': 'true',
                'includeTags': 'true',
                'api_key': WORDNIK_API_KEY,
            }
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code != 200:
                return None
            
            definitions = resp.json()
            if not definitions:
                return None
            
            # Collect all POS
            for defn in definitions:
                pos = defn.get('partOfSpeech', '').lower()
                if pos and pos not in result['all_pos']:
                    result['all_pos'].append(pos)
            
            # Find the best definition
            # Priority: expected_pos match > common definition > first valid
            best_def = None
            best_score = -1
            
            for defn in definitions:
                pos = defn.get('partOfSpeech', '').lower()
                text = defn.get('text', '')
                labels = defn.get('labels', [])
                label_texts = [l.get('text', '') for l in labels] if labels else []
                
                # Skip excluded POS
                if pos in self.EXCLUDED_POS:
                    continue
                
                # Skip if definition is bad
                if self._is_bad_definition(text, word):
                    continue
                
                # Skip uncommon definitions
                if not self._is_common_definition(text, label_texts):
                    continue
                
                # Calculate score
                score = 0
                
                # Bonus for matching expected POS
                if expected_pos and pos == expected_pos:
                    score += 100
                
                # Bonus for common POS
                if pos in ['noun', 'verb', 'adjective']:
                    score += 10
                
                # Bonus for having example
                if defn.get('exampleUses'):
                    score += 5
                
                # Use definition length as tiebreaker (prefer moderate length)
                if 20 <= len(text) <= 150:
                    score += 3
                
                if score > best_score:
                    best_score = score
                    best_def = defn
            
            if best_def:
                result['definition'] = best_def.get('text', '')
                result['pos'] = best_def.get('partOfSpeech', '').lower()
                
                # Get example if available
                examples = best_def.get('exampleUses', [])
                if examples:
                    result['example'] = examples[0].get('text', '')
            
            # Get related words (synonyms/antonyms)
            time.sleep(API_DELAY)
            
            try:
                url = f"{URLS['wordnik']}/{word}/relatedWords"
                params = {
                    'relationshipTypes': 'synonym,antonym',
                    'limitPerRelationshipType': 5,
                    'api_key': WORDNIK_API_KEY,
                }
                
                resp = requests.get(url, params=params, timeout=10)
                
                if resp.status_code == 200:
                    related = resp.json()
                    for rel in related:
                        rel_type = rel.get('relationshipType', '')
                        words = rel.get('words', [])
                        
                        if rel_type == 'synonym':
                            result['synonyms'].extend(words[:5])
                        elif rel_type == 'antonym':
                            result['antonyms'].extend(words[:5])
            except:
                pass
            
            return result
            
        except Exception as e:
            return None
    
    def _fetch_from_free_dictionary(self, word: str, expected_pos: str = None) -> Optional[Dict]:
        """Fetch from Free Dictionary API."""
        try:
            url = f"{URLS['free_dictionary']}/{word}"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            if not data or not isinstance(data, list):
                return None
            
            entry = data[0]
            result = {
                'definition': '',
                'pos': '',
                'synonyms': [],
                'antonyms': [],
                'example': '',
                'all_pos': [],
            }
            
            # Collect all POS first
            for meaning in entry.get('meanings', []):
                pos = meaning.get('partOfSpeech', '').lower()
                if pos and pos not in result['all_pos']:
                    result['all_pos'].append(pos)
            
            # Find the best definition
            best_def = None
            best_pos = None
            best_score = -1
            
            for meaning in entry.get('meanings', []):
                pos = meaning.get('partOfSpeech', '').lower()
                
                # Skip excluded POS
                if pos in self.EXCLUDED_POS:
                    continue
                
                for defn in meaning.get('definitions', []):
                    text = defn.get('definition', '')
                    
                    # Skip bad definitions
                    if self._is_bad_definition(text, word):
                        continue
                    
                    # Calculate score
                    score = 0
                    
                    # Bonus for matching expected POS
                    if expected_pos and pos == expected_pos:
                        score += 100
                    
                    # Bonus for common POS
                    if pos in ['noun', 'verb', 'adjective']:
                        score += 10
                    
                    # Bonus for having example
                    if defn.get('example'):
                        score += 5
                    
                    # Prefer moderate length definitions
                    if 20 <= len(text) <= 150:
                        score += 3
                    
                    if score > best_score:
                        best_score = score
                        best_def = defn
                        best_pos = pos
            
            if best_def:
                result['definition'] = best_def.get('definition', '')
                result['pos'] = best_pos
                result['example'] = best_def.get('example', '')
                
                # Collect synonyms/antonyms
                result['synonyms'].extend(best_def.get('synonyms', []))
                result['antonyms'].extend(best_def.get('antonyms', []))
            
            # Also get meaning-level synonyms/antonyms
            for meaning in entry.get('meanings', []):
                result['synonyms'].extend(meaning.get('synonyms', []))
                result['antonyms'].extend(meaning.get('antonyms', []))
            
            # Deduplicate
            result['synonyms'] = list(dict.fromkeys(result['synonyms']))[:5]
            result['antonyms'] = list(dict.fromkeys(result['antonyms']))[:5]
            
            return result
            
        except Exception as e:
            return None
    
    def get_pos(self, word: str) -> str:
        """Get the primary part of speech for a word."""
        # Check known patterns first
        word_lower = word.lower()
        if word_lower in self.COMMON_POS_PATTERNS:
            return self.COMMON_POS_PATTERNS[word_lower]
        
        result = self.fetch_definition(word)
        return result.get('pos', '') if result else ''
    
    def validate_pos(self, word: str, expected_pos: str) -> bool:
        """Check if a word can be used as a specific POS."""
        result = self.fetch_definition(word)
        if not result:
            return False
        
        all_pos = result.get('all_pos', [])
        return expected_pos in all_pos or result.get('pos') == expected_pos

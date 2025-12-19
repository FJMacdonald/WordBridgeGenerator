"""
Main word generator that orchestrates all fetchers.

This is the core engine that:
1. Fetches definitions from dictionary sources
2. Finds best matching emoji with category
3. Gets relationships (synonyms, antonyms, rhymes)
4. Fetches example sentences from dictionaries
5. Fetches idioms from files and TheFreeDictionary
6. Generates valid distractors
"""

import time
from typing import Optional, Set, List

from ..config import API_DELAY, EXCLUDED_WORDS, MIN_SENTENCE_WORDS
from ..fetchers import (
    EmojiFetcher,
    DictionaryFetcher,
    SentenceFetcher,
    RelationshipFetcher,
    FrequencyFetcher,
    IdiomFetcher,
)
from .sound_detector import SoundGroupDetector
from .distractor_generator import DistractorGenerator
from .wordbank_manager import WordEntry


class WordGenerator:
    """
    Main word generation engine.
    
    Coordinates all fetchers to generate complete word entries.
    No fallbacks - if data can't be fetched, the field is left empty
    and the entry is marked for review.
    """
    
    def __init__(self):
        """Initialize all fetchers."""
        print("\n🚀 Initializing WordBank Generator")
        print("=" * 60)
        
        # Initialize fetchers
        self.emoji_fetcher = EmojiFetcher()
        self.dictionary = DictionaryFetcher()
        self.sentence_fetcher = SentenceFetcher()
        self.relationship_fetcher = RelationshipFetcher()
        self.frequency_fetcher = FrequencyFetcher()
        self.idiom_fetcher = IdiomFetcher()
        
        # Initialize generators
        self.sound_detector = SoundGroupDetector()
        self.distractor_gen = DistractorGenerator(
            self.frequency_fetcher,
            self.dictionary,
            self.sound_detector
        )
        
        # Pre-fetch data
        self.emoji_fetcher.fetch()
        self.frequency_fetcher.fetch()
        self.dictionary.fetch_word_list()
        
        # Track generated words
        self.generated_words: Set[str] = set()
        
        print("=" * 60)
        print("✅ Initialization complete\n")
    
    def generate_entry(self, word: str, 
                       target_pos: str = None) -> Optional[WordEntry]:
        """
        Generate a complete entry for a word.
        
        Args:
            word: The word to generate an entry for
            target_pos: Optional POS filter (noun, verb, adjective)
            
        Returns:
            WordEntry if successful, None if word should be skipped
        """
        word_lower = word.lower().strip()
        
        # Skip excluded words
        if word_lower in EXCLUDED_WORDS:
            return None
        
        # Skip already generated
        if word_lower in self.generated_words:
            return None
        
        # Create entry
        entry = WordEntry(id=word_lower, word=word)
        
        # =========================================
        # Step 1: Fetch definition and POS
        # =========================================
        def_data = self.dictionary.fetch_definition(word)
        
        if not def_data:
            # Word is excluded (wrong POS) or not found
            return None
        
        if not def_data.get('definition'):
            return None
        
        entry.definition = def_data['definition']
        entry.partOfSpeech = def_data.get('pos', 'noun')
        entry.synonyms = def_data.get('synonyms', [])
        entry.antonyms = def_data.get('antonyms', [])
        entry.sources['definition'] = 'freedictionary'
        
        # Check POS filter
        if target_pos and entry.partOfSpeech != target_pos:
            # Check if word can be used as target POS
            all_pos = def_data.get('all_pos', [])
            if target_pos not in all_pos:
                return None
            entry.partOfSpeech = target_pos
        
        time.sleep(API_DELAY)
        
        # =========================================
        # Step 2: Fetch relationships
        # =========================================
        rel_data = self.relationship_fetcher.fetch_all(word)
        
        # Merge with dictionary data
        entry.synonyms = list(dict.fromkeys(
            entry.synonyms + rel_data.get('synonyms', [])
        ))[:5]
        entry.antonyms = list(dict.fromkeys(
            entry.antonyms + rel_data.get('antonyms', [])
        ))[:5]
        entry.associated = rel_data.get('associated', [])[:6]
        entry.rhymes = rel_data.get('rhymes', [])[:7]
        entry.sources['relationships'] = 'datamuse'
        
        time.sleep(API_DELAY)
        
        # =========================================
        # Step 3: Find best emoji with category
        # =========================================
        emoji, category, subcategory = self.emoji_fetcher.find_best_emoji(
            word,
            definition=entry.definition,
            synonyms=entry.synonyms,
            pos=entry.partOfSpeech
        )
        
        if not emoji:
            # No emoji found - skip this word entirely
            # (No fallbacks allowed)
            return None
        
        entry.emoji = emoji
        entry.category = category
        entry.subcategory = subcategory
        entry.sources['emoji'] = 'emojilib+emoji-data'
        
        # =========================================
        # Step 4: Get sound group
        # =========================================
        entry.soundGroup = self.sound_detector.get_sound_group(word)
        
        # =========================================
        # Step 5: Fetch sentences
        # =========================================
        # Get any example from dictionary first
        dict_examples = []
        if def_data.get('example'):
            dict_examples.append(def_data['example'])
        
        # Fetch sentences - must contain EXACT target word
        sentences = self.sentence_fetcher.fetch_sentences(
            word, 
            count=2,
            dictionary_examples=dict_examples
        )
        
        # Validate sentences meet minimum length
        valid_sentences = [
            s for s in sentences 
            if len(s.split()) >= MIN_SENTENCE_WORDS
        ]
        
        if valid_sentences:
            entry.sentences = valid_sentences[:2]
            entry.sources['sentences'] = 'dictionary+tatoeba'
        else:
            # No valid sentences found - leave empty, mark for review
            entry.sentences = []
        
        time.sleep(API_DELAY)
        
        # =========================================
        # Step 6: Generate distractors
        # =========================================
        # Build avoid set
        avoid = {word_lower}
        avoid.update(s.lower() for s in entry.synonyms)
        avoid.update(a.lower() for a in entry.antonyms)
        avoid.update(a.lower() for a in entry.associated)
        avoid.update(r.lower() for r in entry.rhymes)
        
        entry.distractors = self.distractor_gen.generate(
            target_word=word,
            target_pos=entry.partOfSpeech,
            avoid_words=avoid,
            rhymes=entry.rhymes,
            category=entry.category
        )
        entry.sources['distractors'] = 'frequency_filtered'
        
        # =========================================
        # Step 7: Get frequency rank
        # =========================================
        entry.frequencyRank = self.frequency_fetcher.get_rank(word)
        
        # =========================================
        # Step 8: Get idioms/phrases
        # =========================================
        # Idioms come from curated files and TheFreeDictionary
        entry.phrases = self.idiom_fetcher.fetch_idioms(word, language='en')
        if entry.phrases:
            entry.sources['phrases'] = 'idiom_files+thefreedictionary'
        
        # =========================================
        # Step 9: Determine review status
        # =========================================
        # Needs review if missing required data
        entry.needsReview = not entry.is_complete()
        
        # Mark as generated
        self.generated_words.add(word_lower)
        
        return entry
    
    def get_candidate_words(self, count: int, 
                            exclude: Set[str] = None) -> List[str]:
        """
        Get candidate words for generation.
        
        Args:
            count: Number of candidates to return
            exclude: Words to exclude
            
        Returns:
            List of candidate words from frequency list
        """
        exclude = exclude or set()
        exclude.update(EXCLUDED_WORDS)
        exclude.update(self.generated_words)
        
        # Get more candidates than needed (some will fail)
        return self.frequency_fetcher.get_top_words(count * 3, exclude)
    
    def reset(self):
        """Reset generator state for new wordbank."""
        self.generated_words.clear()
        self.distractor_gen.reset_usage()

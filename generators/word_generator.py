"""
Main word generator that orchestrates all fetchers.

This is the core engine that:
1. Fetches definitions from dictionary sources
2. Finds best matching emoji with category
3. Gets relationships (synonyms, antonyms, rhymes)
4. Fetches example sentences from dictionaries
5. Fetches idioms from files and TheFreeDictionary
6. Generates valid distractors

New features:
- Master wordbank integration (skip approved entries)
- API status tracking and user feedback
- Quality mode for synonyms/antonyms
- Overnight mode for rate-limited APIs
"""

import time
from typing import Optional, Set, List, Dict

from ..config import API_DELAY, EXCLUDED_WORDS, MIN_SENTENCE_WORDS
from ..fetchers import (
    EmojiFetcher,
    DictionaryFetcher,
    DataSourceMode,
    SentenceFetcher,
    RelationshipFetcher,
    FrequencyFetcher,
    IdiomFetcher,
    get_api_tracker,
)
from .sound_detector import SoundGroupDetector
from .distractor_generator import DistractorGenerator
from .wordbank_manager import WordEntry
from .master_wordbank import get_master_wordbank, MasterWordbank


class WordGenerator:
    """
    Main word generation engine.
    
    Coordinates all fetchers to generate complete word entries.
    No fallbacks - if data can't be fetched, the field is left empty
    and the entry is marked for review.
    
    New features:
    - Master wordbank: Approved entries are not regenerated
    - API status tracking: Provides feedback on Wordnik auth/rate limits
    - Quality modes: Strict vs standard synonym/antonym filtering
    - Overnight mode: Slow processing to respect rate limits
    """
    
    def __init__(self, 
                 mode: DataSourceMode = DataSourceMode.WORDNIK_PREFERRED,
                 quality_mode: str = "strict",
                 use_master_wordbank: bool = True,
                 language: str = "en"):
        """
        Initialize all fetchers.
        
        Args:
            mode: Data source mode
                - WORDNIK_PREFERRED: Best quality, may hit rate limits
                - FREE_DICTIONARY_ONLY: Faster, standard quality
                - OVERNIGHT: Slow but complete Wordnik processing
            quality_mode: "strict" for fewer but better synonyms/antonyms
            use_master_wordbank: If True, skip regenerating approved entries
            language: Language code for master wordbank
        """
        print("\n🚀 Initializing WordBank Generator")
        print("=" * 60)
        
        self.mode = mode
        self.quality_mode = quality_mode
        self.use_master_wordbank = use_master_wordbank
        self.language = language
        
        # Check API status first
        self._check_api_status()
        
        # Initialize fetchers
        self.emoji_fetcher = EmojiFetcher()
        self.dictionary = DictionaryFetcher(mode=mode)
        self.sentence_fetcher = SentenceFetcher()
        self.relationship_fetcher = RelationshipFetcher(quality_mode=quality_mode)
        self.frequency_fetcher = FrequencyFetcher()
        self.idiom_fetcher = IdiomFetcher()
        
        # Initialize master wordbank
        if use_master_wordbank:
            self.master_wordbank = get_master_wordbank(language)
            print(f"📚 Master wordbank: {self.master_wordbank.count()} approved entries")
        else:
            self.master_wordbank = None
        
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
    
    def _check_api_status(self):
        """Check API status and report to user."""
        tracker = get_api_tracker()
        
        # Check Wordnik
        wordnik_status = tracker.check_wordnik_auth()
        
        print(f"\n📡 API Status:")
        print(f"   Wordnik: {wordnik_status.status.value}")
        if wordnik_status.message:
            print(f"   {wordnik_status.message}")
        
        if wordnik_status.rate_limits:
            rl = wordnik_status.rate_limits
            print(f"   Rate limits: {rl.requests_per_minute}/min, {rl.requests_per_hour}/hour")
        
        # Check Free Dictionary
        fd_status = tracker.check_free_dictionary()
        print(f"   Free Dictionary: {fd_status.status.value}")
        
        # Check Datamuse
        dm_status = tracker.check_datamuse()
        print(f"   Datamuse: {dm_status.status.value}")
        print()
    
    def get_api_status(self) -> Dict:
        """
        Get current API status for UI display.
        
        Returns:
            Dict with status for each API
        """
        tracker = get_api_tracker()
        statuses = tracker.check_all_apis()
        
        return {
            'wordnik': statuses['wordnik'].to_dict(),
            'free_dictionary': statuses['free_dictionary'].to_dict(),
            'datamuse': statuses['datamuse'].to_dict(),
            'recommendation': tracker.get_recommended_mode(),
            'dictionary_status': self.dictionary.get_status(),
        }
    
    def set_mode(self, mode: DataSourceMode):
        """
        Change the data source mode.
        
        Args:
            mode: New mode to use
        """
        self.mode = mode
        self.dictionary.set_mode(mode)
        print(f"🔄 Mode changed to: {mode.value}")
    
    def set_quality_mode(self, quality_mode: str):
        """
        Set synonym/antonym quality mode.
        
        Args:
            quality_mode: "strict" for fewer but better results
        """
        self.quality_mode = quality_mode
        self.relationship_fetcher.set_quality_mode(quality_mode)
        print(f"🔄 Quality mode changed to: {quality_mode}")
    
    def generate_entry(self, word: str, 
                       target_pos: str = None,
                       force_regenerate: bool = False) -> Optional[WordEntry]:
        """
        Generate a complete entry for a word.
        
        Args:
            word: The word to generate an entry for
            target_pos: Optional POS filter (noun, verb, adjective)
            force_regenerate: If True, regenerate even if in master wordbank
            
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
        
        # Check master wordbank - skip if already approved
        if self.master_wordbank and not force_regenerate:
            if self.master_wordbank.is_approved(word_lower):
                # Return the approved entry instead of regenerating
                approved_entry = self.master_wordbank.get_entry(word_lower)
                if approved_entry:
                    self.generated_words.add(word_lower)
                    return WordEntry.from_dict(approved_entry)
        
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
        emoji, category = self.emoji_fetcher.find_best_emoji(
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
        entry.category = category  # Only set for nouns, empty for other POS
        entry.sources['emoji'] = 'BehrouzSohrabi/Emoji'
        
        # =========================================
        # Step 4: Get sound group
        # =========================================
        entry.soundGroup = self.sound_detector.get_sound_group(word)
        
        # =========================================
        # Step 5: Fetch sentences
        # =========================================
        # Get all examples from dictionary (including multiple from definitions)
        dict_examples = def_data.get('examples', [])
        if not dict_examples and def_data.get('example'):
            dict_examples = [def_data['example']]
        
        # Fetch sentences - must contain EXACT target word
        # Goal: 2 sentences (one short, one longer)
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

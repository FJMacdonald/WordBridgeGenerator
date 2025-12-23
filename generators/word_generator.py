"""
Main word generator that orchestrates all fetchers.

API Sources:
- Merriam-Webster Learner's Dictionary: Definitions, POS, Sentences, Phrases
- Merriam-Webster Intermediate Thesaurus: Synonyms, Antonyms
- Datamuse API: Rhymes, Categories (rel_gen)
- USF Free Association Norms: Associated words
- BehrouzSohrabi/Emoji: Emoji matching
- The Noun Project: Fallback images (with attribution)
- Free Dictionary: Fallback for rate limits

Features:
- Rate limit handling with save/resume capability
- Master wordbank integration
- Quality mode for synonym/antonym filtering
- Overnight mode for slow but complete processing
"""

import time
import json
from typing import Optional, Set, List, Dict
from datetime import datetime

from ..config import API_DELAY, EXCLUDED_WORDS, MIN_SENTENCE_WORDS, PROGRESS_FILE
from ..fetchers import (
    EmojiFetcher,
    DictionaryFetcher,
    DataSourceMode,
    RateLimitError,
    SentenceFetcher,
    RelationshipFetcher,
    FrequencyFetcher,
    IdiomFetcher,
    CategoryFetcher,
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
    Handles rate limits gracefully with save/resume capability.
    
    Features:
    - Master wordbank: Approved entries are not regenerated
    - API status tracking: Provides feedback on rate limits
    - Save/Resume: Saves progress when rate limited
    - Overnight mode: Slow processing to respect rate limits
    """
    
    def __init__(self, 
                 mode: DataSourceMode = DataSourceMode.MW_PREFERRED,
                 quality_mode: str = "strict",
                 use_master_wordbank: bool = True,
                 language: str = "en"):
        """
        Initialize all fetchers.
        
        Args:
            mode: Data source mode
                - MW_PREFERRED: Best quality, may hit rate limits
                - FREE_DICTIONARY_ONLY: Faster, standard quality
                - OVERNIGHT: Slow but complete MW processing
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
        self.idiom_fetcher = IdiomFetcher()  # Now minimal - phrases come from MW
        self.category_fetcher = CategoryFetcher()
        
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
        
        # Track words needing manual input
        self.words_needing_review: List[Dict] = []
        
        # Progress tracking for save/resume
        self._current_progress: Dict = {}
        
        print("=" * 60)
        print("✅ Initialization complete\n")
    
    def _check_api_status(self):
        """Check API status and report to user."""
        tracker = get_api_tracker()
        
        print(f"\n📡 API Status:")
        
        # Check MW Learner's
        mw_status = tracker.check_mw_learners_auth()
        print(f"   MW Learner's: {mw_status.status.value}")
        if mw_status.message:
            print(f"   {mw_status.message}")
        
        # Check MW Thesaurus
        mw_thes_status = tracker.check_mw_thesaurus_auth()
        print(f"   MW Thesaurus: {mw_thes_status.status.value}")
        
        # Check Free Dictionary
        fd_status = tracker.check_free_dictionary()
        print(f"   Free Dictionary: {fd_status.status.value}")
        
        # Check Datamuse
        dm_status = tracker.check_datamuse()
        print(f"   Datamuse: {dm_status.status.value}")
        print()
    
    def get_api_status(self) -> Dict:
        """Get current API status for UI display."""
        tracker = get_api_tracker()
        statuses = tracker.check_all_apis()
        
        return {
            'mw_learners': statuses['mw_learners'].to_dict(),
            'mw_thesaurus': statuses['mw_thesaurus'].to_dict(),
            'free_dictionary': statuses['free_dictionary'].to_dict(),
            'datamuse': statuses['datamuse'].to_dict(),
            'recommendation': tracker.get_recommended_mode(),
            'dictionary_status': self.dictionary.get_status(),
            'has_saved_progress': tracker.has_saved_progress(),
        }
    
    def set_mode(self, mode: DataSourceMode):
        """Change the data source mode."""
        self.mode = mode
        self.dictionary.set_mode(mode)
        print(f"🔄 Mode changed to: {mode.value}")
    
    def set_quality_mode(self, quality_mode: str):
        """Set synonym/antonym quality mode."""
        self.quality_mode = quality_mode
        self.relationship_fetcher.set_quality_mode(quality_mode)
        print(f"🔄 Quality mode changed to: {quality_mode}")
    
    def save_progress(self, words_remaining: List[str], wordbank_path: str,
                      settings: Dict) -> bool:
        """
        Save current progress for later resumption.
        
        Called when rate limits are encountered.
        """
        tracker = get_api_tracker()
        
        progress_data = {
            'words_completed': list(self.generated_words),
            'words_remaining': words_remaining,
            'current_wordbank': wordbank_path,
            'settings': settings,
            'rate_limit_info': self.dictionary.get_status(),
            'words_needing_review': self.words_needing_review,
        }
        
        success = tracker.save_progress(progress_data)
        if success:
            print(f"\n💾 Progress saved! {len(self.generated_words)} words completed.")
            print(f"   {len(words_remaining)} words remaining.")
            print(f"   Resume later when rate limits reset.\n")
        
        return success
    
    def load_progress(self) -> Optional[Dict]:
        """Load saved progress for resumption."""
        tracker = get_api_tracker()
        return tracker.load_progress()
    
    def clear_progress(self):
        """Clear saved progress after successful completion."""
        tracker = get_api_tracker()
        tracker.clear_progress()
    
    def generate_entry(self, word: str, 
                       target_pos: str = None,
                       force_regenerate: bool = False) -> Optional[WordEntry]:
        """
        Generate a complete entry for a word.
        
        Args:
            word: The word to generate an entry for
            target_pos: Optional POS filter
            force_regenerate: If True, regenerate even if in master wordbank
            
        Returns:
            WordEntry if successful, None if word should be skipped
            
        Raises:
            RateLimitError: If rate limit exceeded (caller should save progress)
        """
        word_lower = word.lower().strip()
        
        # Skip excluded words
        if word_lower in EXCLUDED_WORDS:
            return None
        
        # Skip already generated
        if word_lower in self.generated_words:
            return None
        
        # Check master wordbank
        if self.master_wordbank and not force_regenerate:
            if self.master_wordbank.is_approved(word_lower):
                approved_entry = self.master_wordbank.get_entry(word_lower)
                if approved_entry:
                    self.generated_words.add(word_lower)
                    return WordEntry.from_dict(approved_entry)
        
        # Create entry
        entry = WordEntry(id=word_lower, word=word)
        
        # =========================================
        # Step 1: Fetch definition, POS, sentences, phrases from MW Learner's
        # =========================================
        try:
            def_data = self.dictionary.fetch_definition(word)
        except RateLimitError as e:
            # Propagate rate limit error for save/resume
            raise e
        
        if not def_data:
            return None
        
        if not def_data.get('definition'):
            return None
        
        entry.definition = def_data['definition']
        entry.partOfSpeech = def_data.get('pos', 'noun')
        entry.sources['definition'] = 'merriam_webster'
        
        # Sentences from MW (vis field)
        if def_data.get('examples'):
            entry.sentences = def_data['examples'][:2]
            entry.sources['sentences'] = 'merriam_webster'
        
        # Phrases from MW (dros field)
        if def_data.get('phrases'):
            entry.phrases = def_data['phrases'][:5]
            entry.sources['phrases'] = 'merriam_webster'
        
        # Check POS filter
        if target_pos and entry.partOfSpeech != target_pos:
            all_pos = def_data.get('all_pos', [])
            if target_pos not in all_pos:
                return None
            entry.partOfSpeech = target_pos
        
        time.sleep(API_DELAY)
        
        # =========================================
        # Step 2: Fetch relationships (synonyms, antonyms from MW Thesaurus,
        #         rhymes from Datamuse, associated from USF)
        # =========================================
        rel_data = self.relationship_fetcher.fetch_all(word)
        
        entry.synonyms = rel_data.get('synonyms', [])[:5]
        entry.antonyms = rel_data.get('antonyms', [])[:5]
        entry.associated = rel_data.get('associated', [])[:6]
        entry.rhymes = rel_data.get('rhymes', [])[:7]
        entry.sources['synonyms'] = 'merriam_webster_thesaurus'
        entry.sources['antonyms'] = 'merriam_webster_thesaurus'
        entry.sources['associated'] = 'usf_free_association'
        entry.sources['rhymes'] = 'datamuse'
        
        time.sleep(API_DELAY)
        
        # =========================================
        # Step 3: Find emoji/image with fallback strategy
        # =========================================
        emoji, emoji_category, noun_project_info = self.emoji_fetcher.find_best_emoji(
            word,
            definition=entry.definition,
            synonyms=entry.synonyms,
            pos=entry.partOfSpeech
        )
        
        if emoji:
            entry.emoji = emoji
            entry.sources['emoji'] = 'BehrouzSohrabi/Emoji'
        elif noun_project_info:
            # Use Noun Project image with attribution
            entry.emoji = ''  # No emoji, use image instead
            entry.sources['image'] = 'noun_project'
            entry.sources['image_attribution'] = noun_project_info.get('attribution', '')
            entry.sources['image_url'] = noun_project_info.get('icon_url', '')
            # Flag for review since it needs attribution display
            self.words_needing_review.append({
                'word': word,
                'reason': 'noun_project_image',
                'details': noun_project_info,
            })
        else:
            # No image found - flag for manual input
            entry.emoji = ''
            self.words_needing_review.append({
                'word': word,
                'reason': 'no_image',
                'details': 'Manual image input required',
            })
        
        # =========================================
        # Step 4: Get category from Datamuse rel_gen
        # =========================================
        if entry.partOfSpeech == 'noun':
            entry.category = self.category_fetcher.get_category_with_fallback(
                word, 
                emoji_category,
                entry.partOfSpeech
            )
            entry.sources['category'] = 'datamuse'
        
        # =========================================
        # Step 5: Get sound group
        # =========================================
        entry.soundGroup = self.sound_detector.get_sound_group(word)
        
        # =========================================
        # Step 6: Fetch additional sentences if needed
        # =========================================
        if len(entry.sentences) < 2:
            # Try to get more sentences from dictionary examples
            additional = self.sentence_fetcher.fetch_sentences(
                word, 
                count=2 - len(entry.sentences),
                dictionary_examples=def_data.get('examples', [])
            )
            for sent in additional:
                if sent not in entry.sentences:
                    entry.sentences.append(sent)
            
            if entry.sentences:
                entry.sources['sentences'] = 'dictionary+tatoeba'
        
        time.sleep(API_DELAY)
        
        # =========================================
        # Step 7: Generate distractors (uses Free Dictionary for POS)
        # =========================================
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
        # Step 8: Get frequency rank
        # =========================================
        entry.frequencyRank = self.frequency_fetcher.get_rank(word)
        
        # =========================================
        # Step 9: Determine review status
        # =========================================
        entry.needsReview = not entry.is_complete()
        
        if entry.needsReview:
            self.words_needing_review.append({
                'word': word,
                'reason': 'incomplete',
                'details': {
                    'has_definition': bool(entry.definition),
                    'has_emoji': bool(entry.emoji),
                    'sentence_count': len(entry.sentences),
                    'distractor_count': len(entry.distractors),
                },
            })
        
        # Mark as generated
        self.generated_words.add(word_lower)
        
        return entry
    
    def get_candidate_words(self, count: int, 
                            exclude: Set[str] = None) -> List[str]:
        """Get candidate words for generation."""
        exclude = exclude or set()
        exclude.update(EXCLUDED_WORDS)
        exclude.update(self.generated_words)
        
        return self.frequency_fetcher.get_top_words(count * 3, exclude)
    
    def get_words_needing_review(self) -> List[Dict]:
        """Get list of words that need manual review."""
        return self.words_needing_review.copy()
    
    def get_words_with_attribution(self) -> Dict[str, Dict]:
        """Get words using Noun Project images (need attribution)."""
        return self.emoji_fetcher.get_words_with_attribution()
    
    def reset(self):
        """Reset generator state for new wordbank."""
        self.generated_words.clear()
        self.words_needing_review.clear()
        self.distractor_gen.reset_usage()

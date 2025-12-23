"""
Data fetcher modules for WordBank Generator.

API Sources:
- Merriam-Webster Learner's Dictionary: Definitions, POS, Sentences, Phrases
- Merriam-Webster Intermediate Thesaurus: Synonyms, Antonyms
- Datamuse API: Rhymes, Categories (rel_gen)
- USF Free Association Norms: Associated words (local CSV files)
- BehrouzSohrabi/Emoji: Emoji matching
- The Noun Project: Fallback images (with attribution)
- Free Dictionary: Fallback for rate limits
"""

from .emoji_fetcher import EmojiFetcher
from .dictionary_fetcher import DictionaryFetcher, DataSourceMode, RateLimitError
from .sentence_fetcher import SentenceFetcher
from .relationship_fetcher import RelationshipFetcher
from .frequency_fetcher import FrequencyFetcher
from .translation_fetcher import TranslationFetcher
from .idiom_fetcher import IdiomFetcher
from .category_fetcher import CategoryFetcher
from .api_status import (
    APIStatus, 
    APIStatusInfo, 
    RateLimitInfo, 
    APIStatusTracker,
    ProgressSaver,
    get_api_tracker
)

__all__ = [
    'EmojiFetcher',
    'DictionaryFetcher',
    'DataSourceMode',
    'RateLimitError',
    'SentenceFetcher',
    'RelationshipFetcher',
    'FrequencyFetcher',
    'TranslationFetcher',
    'IdiomFetcher',
    'CategoryFetcher',
    'APIStatus',
    'APIStatusInfo',
    'RateLimitInfo',
    'APIStatusTracker',
    'ProgressSaver',
    'get_api_tracker',
]

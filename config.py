"""
Configuration settings for WordBank Generator.
"""

from pathlib import Path
import os
from dotenv import load_dotenv 

# Directory paths
BASE_DIR = Path(__file__).parent
  

VERSION = "3.3.0"

# Directory paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
SESSION_FILE = DATA_DIR / "session_state.json"
PROGRESS_FILE = DATA_DIR / "generation_progress.json"
FREE_ASSOCIATION_DIR = DATA_DIR / "FreeAssociation"
load_dotenv(BASE_DIR / ".env")

# Create directories
DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# API rate limiting (seconds between calls)
API_DELAY = 0.3

# Cache expiry (seconds) - 24 hours
CACHE_EXPIRY = 86400

# Data source URLs
URLS = {
    # Emoji data - BehrouzSohrabi/Emoji has text descriptions for finding most generic match
    "emoji_categories": "https://raw.githubusercontent.com/BehrouzSohrabi/Emoji/main/emoji-list-categories.json",
    # Legacy sources (kept for reference)
    "emoji_data": "https://raw.githubusercontent.com/iamcal/emoji-data/master/emoji.json",
    "emojilib": "https://raw.githubusercontent.com/muan/emojilib/main/dist/emoji-en-US.json",
    
    # Dictionary/words
    "english_words": "https://raw.githubusercontent.com/dwyl/english-words/master/words_dictionary.json",
    "free_dictionary": "https://api.dictionaryapi.dev/api/v2/entries/en",
    
    # Merriam-Webster APIs (require API keys)
    "mw_learners": "https://www.dictionaryapi.com/api/v3/references/learners/json",
    "mw_thesaurus": "https://www.dictionaryapi.com/api/v3/references/ithesaurus/json",
    
    # The Noun Project API
    "noun_project": "https://api.thenounproject.com/v2/icon",
    
    # Sentences
    "tatoeba": "https://tatoeba.org/eng/api_v0/search",
    "sentence_dict": "https://sentence.dict.cn/english",
    
    # Relationships
    "datamuse": "https://api.datamuse.com/words",
    
    # Frequency
    "frequency": "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-no-swears.txt",
    
    # Translation services (LibreTranslate is self-hosted)
    "libretranslate": "http://localhost:5000/translate",  # Self-hosted instance
    "mymemory": "https://api.mymemory.translated.net/get",
    "deepl": "https://api-free.deepl.com/v2/translate",
}

# API Keys and URLs (should be set via environment variables in production)
MERRIAM_WEBSTER_LEARNERS_KEY = os.environ.get("MW_LEARNERS_API_KEY", "")
MERRIAM_WEBSTER_THESAURUS_KEY = os.environ.get("MW_THESAURUS_API_KEY", "")
NOUN_PROJECT_KEY = os.environ.get("NOUN_PROJECT_API_KEY", "")
NOUN_PROJECT_SECRET = os.environ.get("NOUN_PROJECT_API_SECRET", "")
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "")
MYMEMORY_EMAIL = os.environ.get("MYMEMORY_EMAIL", "")
LIBRETRANSLATE_URL = os.environ.get("LIBRETRANSLATE_URL", "http://localhost:5000/translate")

# Deprecated - kept for backward compatibility
WORDNIK_API_KEY = os.environ.get("WORDNIK_API_KEY", "")

# Words to exclude (pronouns, auxiliaries, function words, prepositions)
EXCLUDED_WORDS = {
    # Pronouns
    'i', 'me', 'my', 'mine', 'myself', 'you', 'your', 'yours', 'yourself',
    'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself',
    'it', 'its', 'itself', 'we', 'us', 'our', 'ours', 'ourselves',
    'they', 'them', 'their', 'theirs', 'themselves',
    'who', 'whom', 'whose', 'which', 'what', 'that', 'this', 'these', 'those',
    
    # Auxiliary/Modal verbs
    'be', 'am', 'is', 'are', 'was', 'were', 'been', 'being',
    'have', 'has', 'had', 'having',
    'do', 'does', 'did', 'doing', 'done',
    'will', 'would', 'shall', 'should', 'can', 'could', 'may', 'might', 'must',
    
    # Prepositions
    'about', 'above', 'across', 'after', 'against', 'along', 'among', 'around',
    'at', 'before', 'behind', 'below', 'beneath', 'beside', 'between', 'beyond',
    'by', 'down', 'during', 'except', 'for', 'from', 'in', 'inside', 'into',
    'like', 'near', 'of', 'off', 'on', 'onto', 'out', 'outside', 'over',
    'past', 'since', 'through', 'throughout', 'till', 'to', 'toward', 'towards',
    'under', 'underneath', 'until', 'up', 'upon', 'with', 'within', 'without',
    
    # Conjunctions
    'and', 'or', 'but', 'nor', 'so', 'yet', 'for', 'if', 'then', 'else',
    'because', 'although', 'though', 'unless', 'while', 'whereas', 'whether',
    
    # Articles and determiners
    'the', 'a', 'an', 'some', 'any', 'no', 'every', 'each', 'either', 'neither',
    'both', 'few', 'many', 'much', 'more', 'most', 'other', 'another',
    'such', 'all', 'half', 'several', 'enough',
    
    # Adverbs (common function-like)
    'very', 'too', 'quite', 'rather', 'just', 'only', 'also', 'even', 'still',
    'already', 'always', 'never', 'ever', 'often', 'sometimes', 'usually',
    'again', 'further', 'once', 'here', 'there', 'now', 'then', 'well',
    'how', 'when', 'where', 'why',
    
    # Common abstract/function words
    'get', 'got', 'make', 'made', 'go', 'went', 'gone',
    'know', 'think', 'see', 'come', 'take', 'want', 'use',
    'thing', 'things', 'way', 'ways', 'something', 'anything', 'nothing',
    'everything', 'someone', 'anyone', 'everyone', 'nobody',
    'back', 'being', 'going',
    
    # Numbers as words (we want digit emojis for these)
    # Keeping them excluded as they need special handling
}

# Minimum sentence length (words)
MIN_SENTENCE_WORDS = 4

# Distractor length tolerance progression
DISTRACTOR_LENGTH_TOLERANCES = [0, 1, 2]  # Try exact match, then ±1, then ±2

# Maximum distractors needed
MAX_DISTRACTORS = 10

# USF Free Association Norms file mapping
USF_FILE_MAPPING = {
    'A': 'Cue Target Pairs A-B.csv',
    'B': 'Cue Target Pairs A-B.csv',
    'C': 'Cue Target Pairs C.csv',
    'D': 'Cue Target Pairs D-F.csv',
    'E': 'Cue Target Pairs D-F.csv',
    'F': 'Cue Target Pairs D-F.csv',
    'G': 'Cue Target Pairs G-K.csv',
    'H': 'Cue Target Pairs G-K.csv',
    'I': 'Cue Target Pairs G-K.csv',
    'J': 'Cue Target Pairs G-K.csv',
    'K': 'Cue Target Pairs G-K.csv',
    'L': 'Cue Target Pairs L-O.csv',
    'M': 'Cue Target Pairs L-O.csv',
    'N': 'Cue Target Pairs L-O.csv',
    'O': 'Cue Target Pairs L-O.csv',
    'P': 'Cue Target Pairs P-R.csv',
    'Q': 'Cue Target Pairs P-R.csv',
    'R': 'Cue Target Pairs P-R.csv',
    'S': 'Cue Target Pairs S.csv',
    'T': 'Cue Target Pairs T-Z.csv',
    'U': 'Cue Target Pairs T-Z.csv',
    'V': 'Cue Target Pairs T-Z.csv',
    'W': 'Cue Target Pairs T-Z.csv',
    'X': 'Cue Target Pairs T-Z.csv',
    'Y': 'Cue Target Pairs T-Z.csv',
    'Z': 'Cue Target Pairs T-Z.csv',
}

# Rate limit settings
RATE_LIMITS = {
    'merriam_webster': {
        'requests_per_day': 1000,  # Free tier limit
        'requests_per_minute': 30,  # Conservative estimate
    },
    'noun_project': {
        'requests_per_month': 5000,  # Free tier
        'requests_per_minute': 60,
    },
    'datamuse': {
        'requests_per_minute': 100,  # No hard limits but be respectful
    },
    'free_dictionary': {
        'requests_per_minute': 100,  # No hard limits
    },
}

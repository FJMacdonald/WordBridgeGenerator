# WordBridgeGenerator Changes Summary

## Overview

This update refactors the wordbank generator to use the Oxford 3000 word list as the primary source and removes ALL hardcoded word-specific rules and mappings. All words are now processed through the same uniform set of rules without any special cases.

## Key Changes

### 1. New Oxford 3000-Based Generator (`generators/oxford_wordbank_generator.py`)

A new generator that:
- Extracts nouns, verbs, and adjectives from the Oxford 3000 CSV
- Uses the **first POS** when multiple are listed (e.g., "verb, noun" → "verb")
- Generates entries with uniform rules for all words
- Includes test mode to save all API responses for verification
- Generates an issues report tracking problems during generation
- Debug statements for associated word lookups

### 2. Removed ALL Special Case Word Lists and Mappings

The following have been **completely removed**:

#### From `fetchers/relationship_fetcher.py`:
- `STRONG_SYNONYM_PAIRS` - Hardcoded synonym mappings
- `STRONG_ANTONYM_PAIRS` - Hardcoded antonym mappings

#### From `fetchers/dictionary_fetcher.py`:
- `COMMON_POS_PATTERNS` - Hardcoded POS assignments

#### From `fetchers/category_fetcher.py`:
- `KNOWN_CATEGORIES` - Hardcoded category mappings
- `CATEGORY_PRIORITY` - Category prioritization list
- `emoji_category_map` - Emoji category normalization mapping

### 3. Synonyms/Antonyms Handling

- Oxford CSV synonyms/antonyms are used as the base
- "none" values in the CSV are converted to empty lists `[]`
- MW Thesaurus results are merged (removing duplicates)
- No special cases for any words

### 4. Emoji Fallback Strategy

Uses a 3-tier fallback:
1. **BehrouzSohrabi/Emoji** (primary)
2. **OpenMoji** (secondary)
3. **Noun Project** (tertiary, requires attribution)
4. Leave blank if all three fail

Note: BehrouzSohrabi and OpenMoji are NOT logged in api_responses.

### 5. Category Field Changed to Array

The `category` field is now an array containing multiple category sources:

```json
"category": [
  {"source": "BehrouzSohrabi", "category": "Animals & Nature"},
  {"source": "Datamuse", "category": "animal"},
  {"source": "WordNet", "category": "canine"}
]
```

Sources included (no normalization/mapping):
- **BehrouzSohrabi** - From emoji metadata (as-is)
- **Datamuse** - Using rel_gen API (first result)
- **WordNet** - Using NLTK WordNet hypernyms (when available)

### 6. Associated Words from Free Association Files

Associated words are extracted from the USF Free Association Norms CSV files in `data/FreeAssociation/`:
- Uses CUE → TARGET pairs
- Ranked by FSG (Forward Strength) for relevance
- Top 5 associations returned per word
- Debug output shows lookup details in test mode

### 7. Issue Report Generation

A JSON report is generated at `data/generation_issues_report.json` containing:
- API errors encountered (including missing API keys, network errors)
- Words without emoji
- Words without definition
- Words without associated words
- Words without categories
- Words without synonyms/antonyms

### 8. API Response Logging (Test Mode)

All API calls are logged to `data/test_api_responses.json`:
- MW Learners dictionary calls
- MW Thesaurus calls
- Datamuse category/rhymes calls
- Noun Project calls
- WordNet lookups

Note: BehrouzSohrabi and OpenMoji emoji data fetches are NOT logged.

### 9. Test Mode

Run with:
```bash
python -m WordBridgeGenerator --test-oxford      # 10 words
python -m WordBridgeGenerator --test-oxford 20   # 20 words
```

Test mode:
- Limits processing to specified word count
- Saves all API responses to `data/test_api_responses.json`
- Outputs wordbank to `data/test_wordbank_oxford.json`
- Generates issues report to `data/generation_issues_report.json`
- Prints debug output for associated word lookups

## File Changes

| File | Change |
|------|--------|
| `generators/oxford_wordbank_generator.py` | **NEW** - Main Oxford-based generator with debug output |
| `generators/__init__.py` | Added exports for new generator |
| `generators/wordbank_manager.py` | Updated `category` to support arrays |
| `fetchers/relationship_fetcher.py` | Removed `STRONG_SYNONYM_PAIRS`, `STRONG_ANTONYM_PAIRS` |
| `fetchers/dictionary_fetcher.py` | Removed `COMMON_POS_PATTERNS` |
| `fetchers/category_fetcher.py` | Removed `KNOWN_CATEGORIES`, `CATEGORY_PRIORITY`, `emoji_category_map` |
| `fetchers/emoji_fetcher.py` | Added OpenMoji fallback support |
| `__main__.py` | Added `--test-oxford` CLI option |

## Data Requirements

### Oxford 3000 CSV (`data/Oxford3000.csv`)
Required columns:
- `Word` - The word
- `Part of Speech` - POS (comma-separated if multiple)
- `Definition` - Word definition
- `Synonyms` - Comma-separated synonyms or "none"
- `Antonyms` - Comma-separated antonyms or "none"

### Free Association Files (`data/FreeAssociation/`)
Expected files:
- `Cue Target Pairs A-B.csv`
- `Cue Target Pairs C.csv`
- `Cue Target Pairs D-F.csv`
- `Cue Target Pairs G-K.csv`
- `Cue Target Pairs L-O.csv`
- `Cue Target Pairs P-R.csv`
- `Cue Target Pairs S.csv`
- `Cue Target Pairs T-Z.csv`

Required columns:
- `CUE` - The cue word (uppercase)
- `TARGET` - Associated word
- `FSG` - Forward strength (association probability)

## Environment Variables

Required API keys:
- `MW_LEARNERS_API_KEY` - Merriam-Webster Learner's Dictionary
- `MW_THESAURUS_API_KEY` - Merriam-Webster Thesaurus
- `NOUN_PROJECT_API_KEY` - Noun Project API key
- `NOUN_PROJECT_API_SECRET` - Noun Project API secret

## Notes

- WordNet categories only work when NLTK WordNet data is downloaded (`nltk.download('wordnet')`)
- Network access required for emoji data (BehrouzSohrabi, OpenMoji) and all APIs
- All API failures are logged in both issues report and api_responses
- Free Association files must be placed in `data/FreeAssociation/` directory

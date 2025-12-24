# WordBridgeGenerator Changes Summary

## Overview

This update refactors the wordbank generator to use the Oxford 3000 word list as the primary source and removes all hardcoded word-specific rules. All words are now processed through the same uniform set of rules.

## Key Changes

### 1. New Oxford 3000-Based Generator (`generators/oxford_wordbank_generator.py`)

A new generator that:
- Extracts nouns, verbs, and adjectives from the Oxford 3000 CSV
- Uses the **first POS** when multiple are listed (e.g., "verb, noun" → "verb")
- Generates entries with uniform rules for all words
- Includes test mode to save all API responses for verification
- Generates an issues report tracking problems during generation

### 2. Removed Special Case Word Lists

The following hardcoded word lists have been **removed**:

#### From `fetchers/relationship_fetcher.py`:
- `STRONG_SYNONYM_PAIRS` - Hardcoded synonym mappings for specific words
- `STRONG_ANTONYM_PAIRS` - Hardcoded antonym mappings for specific words

#### From `fetchers/dictionary_fetcher.py`:
- `COMMON_POS_PATTERNS` - Hardcoded POS assignments for common words

#### From `fetchers/category_fetcher.py`:
- `KNOWN_CATEGORIES` - Hardcoded category mappings for common nouns

### 3. Synonyms/Antonyms Handling

- Oxford CSV synonyms/antonyms are used as the base
- "none" values in the CSV are converted to empty lists `[]`
- MW Thesaurus results are merged (removing duplicates)
- No special cases for any words

### 4. Emoji Fallback Strategy

Updated to use a 3-tier fallback:
1. **BehrouzSohrabi/Emoji** (primary)
2. **OpenMoji** (secondary)
3. **Noun Project** (tertiary, requires attribution)
4. Leave blank if all three fail (no manual input flagging)

### 5. Category Field Changed to Array

The `category` field is now an array containing multiple category sources:

```json
"category": [
  {"source": "BehrouzSohrabi", "category": "Animals & Nature"},
  {"source": "Datamuse", "category": "animal"},
  {"source": "WordNet", "category": "canine"}
]
```

Sources included:
- **BehrouzSohrabi** - From emoji metadata
- **Datamuse** - Using rel_gen (hypernym) API
- **WordNet** - Using NLTK WordNet (when available)

### 6. Associated Words from Free Association Files

Associated words are extracted from the USF Free Association Norms CSV files in `data/FreeAssociation/`:
- Uses CUE → TARGET pairs
- Ranked by FSG (Forward Strength) for relevance
- Top 5 associations returned per word

### 7. Issue Report Generation

A JSON report is generated at `data/generation_issues_report.json` containing:
- API errors encountered
- Words without emoji
- Words without definition
- Words without associated words
- Words without categories
- Words without synonyms/antonyms

### 8. Test Mode

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

## File Changes

| File | Change |
|------|--------|
| `generators/oxford_wordbank_generator.py` | **NEW** - Main Oxford-based generator |
| `generators/__init__.py` | Added exports for new generator |
| `generators/wordbank_manager.py` | Updated `category` to support arrays |
| `fetchers/relationship_fetcher.py` | Removed `STRONG_SYNONYM_PAIRS`, `STRONG_ANTONYM_PAIRS` |
| `fetchers/dictionary_fetcher.py` | Removed `COMMON_POS_PATTERNS` |
| `fetchers/category_fetcher.py` | Removed `KNOWN_CATEGORIES` |
| `fetchers/emoji_fetcher.py` | Added OpenMoji fallback support |
| `__main__.py` | Added `--test-oxford` CLI option |

## Output Format

```json
{
  "version": "3.0",
  "language": "en",
  "generatedAt": "2024-01-01T00:00:00.000000",
  "generationMethod": "oxford_3000",
  "totalEntries": 10,
  "words": [
    {
      "id": "abandon",
      "word": "abandon",
      "partOfSpeech": "verb",
      "definition": "Cease to support or look after (someone); desert",
      "soundGroup": "a",
      "visual": {
        "emoji": "",
        "asset": null
      },
      "relationships": {
        "synonyms": ["desert", "leave"],
        "antonyms": ["support", "keep"],
        "associated": ["give", "leave", "quit"],
        "rhymes": ["band", "hand", "land"]
      },
      "distractors": [],
      "sentences": ["He abandoned his family."],
      "phrases": ["abandon ship"],
      "frequencyRank": 99999,
      "needsReview": true,
      "sources": {
        "definition": "oxford_3000",
        "synonyms": "oxford_3000+merriam_webster_thesaurus",
        "antonyms": "oxford_3000+merriam_webster_thesaurus",
        "associated": "usf_free_association",
        "rhymes": "datamuse",
        "emoji": "not_found",
        "category": "BehrouzSohrabi+Datamuse+WordNet"
      },
      "category": [
        {"source": "Datamuse", "category": "verb"},
        {"source": "WordNet", "category": "leave"}
      ]
    }
  ]
}
```

## Data Requirements

### Oxford 3000 CSV (`data/Oxford3000.csv`)
Required columns:
- `Word` - The word
- `Part of Speech` - POS (comma-separated if multiple)
- `Definition` - Word definition
- `Synonyms` - Comma-separated synonyms or "none"
- `Antonyms` - Comma-separated antonyms or "none"

### Free Association Files (`data/FreeAssociation/`)
CSV files with columns including:
- `CUE` - The cue word
- `TARGET` - Associated word
- `FSG` - Forward strength (association strength)

## Notes

- WordNet categories only work when NLTK WordNet data is downloaded
- Network access required for emoji data (BehrouzSohrabi, OpenMoji)
- MW API keys required for definitions and thesaurus lookups
- All API failures are logged in the issues report

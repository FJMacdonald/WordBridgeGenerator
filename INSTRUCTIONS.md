# WordBank Generator v3.3.0

A comprehensive tool for generating speech therapy wordbanks with rich linguistic data.

## API Sources

### Primary APIs (Require API Keys)

1. **Merriam-Webster Learner's Dictionary** (`MW_LEARNERS_API_KEY`)
   - Definitions with usage labels
   - Part of speech
   - Example sentences (vis field)
   - Phrases/idioms (dros - defined run-ons)

2. **Merriam-Webster Intermediate Thesaurus** (`MW_THESAURUS_API_KEY`)
   - Synonyms
   - Antonyms

3. **The Noun Project** (`NOUN_PROJECT_API_KEY`, `NOUN_PROJECT_API_SECRET`)
   - Fallback images when no emoji found
   - Requires attribution display

### Free APIs (No API Key Required)

4. **Datamuse API**
   - Rhymes (`rel_rhy`)
   - Categories (`rel_gen` for hypernym/generalization)

5. **Free Dictionary API**
   - Fallback for definitions when MW is rate limited
   - POS verification for distractors

### Local Data Sources

6. **USF Free Association Norms** (`data/FreeAssociation/`)
   - Associated words
   - Uses #G count to rank top 3-5 associations
   - Files: `Cue Target Pairs A-B.csv`, `Cue Target Pairs C.csv`, etc.

7. **BehrouzSohrabi/Emoji Database**
   - Primary emoji source
   - Categories and keywords for matching

## Environment Variables

```bash
# Merriam-Webster APIs (get keys at dictionaryapi.com)
export MW_LEARNERS_API_KEY="your-learners-key"
export MW_THESAURUS_API_KEY="your-thesaurus-key"

# The Noun Project (get keys at thenounproject.com/developers)
export NOUN_PROJECT_API_KEY="your-key"
export NOUN_PROJECT_API_SECRET="your-secret"

# Optional: Translation services
export DEEPL_API_KEY="your-key"
export MYMEMORY_EMAIL="your-email"
```

## Data Flow

### Word Entry Generation

1. **Definition, POS, Sentences, Phrases** → MW Learner's Dictionary
2. **Synonyms, Antonyms** → MW Thesaurus (+ curated fallbacks)
3. **Associated Words** → USF Free Association Norms (top 3-5 by #G count)
4. **Rhymes** → Datamuse API
5. **Category** → Datamuse API (rel_gen) with emoji category fallback
6. **Emoji/Image**:
   - First: BehrouzSohrabi/Emoji database
   - Second: The Noun Project API (with attribution)
   - Third: Flag for manual input
7. **Distractors** → Frequency list filtered by 8 rules

### Distractor Generation Rules

All 8 rules must be satisfied:

1. **NOT synonyms or antonyms** of target word
2. **NOT starting with same sound** as target word
3. **NOT rhyming** with target word
4. **NOT in same category** as target word (Datamuse rel_gen)
5. **NOT semantically associated** with target word
6. **Same length** first, then ±1, then ±2 as fallback
7. **Same part of speech** as target word (Free Dictionary verification)
8. **Minimize repetition** across wordbank

## Rate Limits

### Merriam-Webster (Free Tier)
- 1,000 requests/day per API
- ~30 requests/minute recommended

### The Noun Project (Free Tier)
- 5,000 requests/month
- ~60 requests/minute

### Rate Limit Handling

When rate limits are encountered:

1. **Save Progress**: Current generation state is saved automatically
2. **Resume Later**: Use "Resume" button when limits reset
3. **Switch Mode**: Change to Free Dictionary mode for lower quality but no limits
4. **Overnight Mode**: Slow processing with long delays

## File Structure

```
WordBridgeGenerator/
├── app.py                    # Flask web application
├── config.py                 # Configuration and API keys
├── fetchers/
│   ├── dictionary_fetcher.py # MW Learner's + Free Dict
│   ├── relationship_fetcher.py # MW Thesaurus + USF + Datamuse
│   ├── emoji_fetcher.py      # Emoji + Noun Project
│   ├── category_fetcher.py   # Datamuse rel_gen
│   ├── idiom_fetcher.py      # Minimal (phrases from MW)
│   ├── sentence_fetcher.py   # Additional sentence fetching
│   ├── frequency_fetcher.py  # Word frequency list
│   └── api_status.py         # Rate limit tracking
├── generators/
│   ├── word_generator.py     # Main orchestrator
│   ├── distractor_generator.py # 8-rule distractor logic
│   ├── wordbank_manager.py   # JSON file management
│   └── sound_detector.py     # Sound group detection
├── data/
│   ├── FreeAssociation/      # USF CSV files
│   │   ├── Cue Target Pairs A-B.csv
│   │   ├── Cue Target Pairs C.csv
│   │   └── ... (more files)
│   └── cache/                # API response cache
└── templates/                # HTML templates
```

## USF Free Association Norms

The USF data files contain word association norms with these columns:

```csv
CUE, TARGET, NORMED?, #G, #P, FSG, BSG, MSG, OSG, ...
```

Key column: **#G** = Number of participants who gave this response

Example:
```csv
ABDOMEN, BODY, YES, 152, 11, .072, ...
ABDOMEN, MUSCLE, YES, 152, 7, .046, ...
```

The code selects top 3-5 targets with highest #G count.

## Emoji/Image Fallback Strategy

1. **BehrouzSohrabi/Emoji Database**
   - Search by keyword
   - Use `text` field to find most generic match
   - Prioritize non-flag emojis

2. **The Noun Project API**
   - OAuth 1.0 authentication
   - Returns icon URL + attribution
   - **Attribution must be displayed**

3. **Manual Input Required**
   - Word added to review list
   - No fallback emoji used

## Output Format

```json
{
  "id": "happy",
  "word": "happy",
  "partOfSpeech": "adjective",
  "category": "",
  "definition": "feeling pleasure and enjoyment",
  "soundGroup": "h",
  "visual": {
    "emoji": "😊",
    "asset": null,
    "imageUrl": "",
    "attribution": ""
  },
  "relationships": {
    "synonyms": ["joyful", "cheerful", "glad"],
    "antonyms": ["sad", "unhappy"],
    "associated": ["smile", "joy", "birthday"],
    "rhymes": ["snappy", "sappy"]
  },
  "distractors": ["hungry", "yellow", "simple", ...],
  "sentences": [
    "She was happy to see her friend.",
    "The happy children played in the park."
  ],
  "phrases": ["happy as a clam", "happy medium"],
  "frequencyRank": 234,
  "needsReview": false,
  "sources": {
    "definition": "merriam_webster",
    "synonyms": "merriam_webster_thesaurus",
    "associated": "usf_free_association",
    "rhymes": "datamuse",
    "category": "datamuse"
  }
}
```

## Running the Application

```bash
# Set environment variables
export MW_LEARNERS_API_KEY="your-key"
export MW_THESAURUS_API_KEY="your-key"

# Run the web app
cd WordBridgeGenerator
python -m WordBridgeGenerator

# Or directly
python app.py
```

Access at: http://localhost:5001

## API Endpoints

### Generation
- `POST /api/generate/start` - Start generation
- `GET /api/generate/status` - Get progress
- `POST /api/generate/resume` - Resume from saved progress
- `POST /api/generate/set-mode` - Change mode during generation
- `POST /api/generate/clear-progress` - Clear saved progress

### API Status
- `GET /api/status` - All API statuses
- `GET /api/status/mw` - MW API details

### Review
- `GET /api/review/list` - Words needing manual review
- `GET /api/review/attribution` - Words using Noun Project (need attribution)

### Utilities
- `GET /api/category?word=dog` - Get category for word
- `GET /api/emoji/search?q=happy` - Search emojis
- `POST /api/distractors` - Generate distractors

## Changes from v3.2.0

### Removed
- Wordnik API (rate limit issues)
- Local idiom file searching
- TheFreeDictionary idiom scraping

### Added
- Merriam-Webster Learner's Dictionary API
- Merriam-Webster Intermediate Thesaurus API
- USF Free Association Norms for associations
- Datamuse rel_gen for categories
- The Noun Project API for fallback images
- Save/Resume for rate limit handling
- Image attribution support
- Words needing review tracking

### Changed
- Synonyms/Antonyms: Wordnik → MW Thesaurus
- Definitions: Wordnik → MW Learner's
- Sentences: Now from MW Learner's (vis field)
- Phrases: Now from MW Learner's (dros field)
- Categories: Emoji categories → Datamuse rel_gen
- Associated: Datamuse rel_trg → USF Free Association Norms

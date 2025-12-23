# WordBank Generator - Instructions

## Overview

The WordBank Generator creates carefully curated word data for aphasia recovery exercises. 
Data quality is paramount - incorrect data can confuse and frustrate patients.

## Version 3.2.0 New Features

### API Status & Rate Limit Handling

The system now provides clear feedback on API availability:

- **Wordnik Auth Errors**: If your API key is invalid, you'll see a clear message
- **Rate Limits**: When Wordnik rate limits are hit, you see:
  - Current limits (e.g., "15/min, 100/hour")
  - Options to wait, use overnight mode, or switch to Free Dictionary
- **Mode Switching**: Change data source mode during generation

### Data Source Modes

| Mode | Quality | Speed | Rate Limits |
|------|---------|-------|-------------|
| **Wordnik Preferred** | Highest | Normal | May hit limits |
| **Free Dictionary Only** | Standard | Fast | No limits |
| **Overnight Mode** | Highest | Very Slow | Stays within limits |

### Master Wordbank

Approved entries are stored separately and never overwritten:

- **Approve entries** in the Edit tab (⭐ button)
- **Protected fields**: synonyms, antonyms, definition, emoji, sentences
- **Auto-merge**: Approved entries are used during generation
- **Notes**: Add curator notes to explain approval decisions

### Stricter Synonym/Antonym Quality

The relationship fetcher now uses **strict quality filtering**:

- Curated lists of strong synonym/antonym pairs
- Filters out "weak" relationships (e.g., "decent" is NOT a synonym for "best")
- Semantic similarity scoring
- Score thresholds for API results

## Key Principles

### NO FALLBACKS - Quality Over Quantity

If data cannot be properly fetched, fields are left empty and entries are marked for review. 
It's better to have incomplete data than incorrect data.

### NO HARDCODED VALUES - Purely Algorithmic

The system relies **entirely** on external data sources. There are no:
- Hardcoded word-to-emoji mappings
- Hardcoded phrase databases

All matching and filtering is done algorithmically based on the source data.

### Data Sources

| Data Type | Source | Method |
|-----------|--------|--------|
| Definitions | Wordnik, Free Dictionary | First valid definition from API |
| POS | Wordnik, Free Dictionary | As reported by dictionary |
| Synonyms/Antonyms | Wordnik, Free Dictionary, Datamuse | Strict quality filtering |
| Sentences | Dictionary examples, Tatoeba | Exact word match, 4+ words, 2 per word |
| Idioms | Local files, TheFreeDictionary | File search + web scraping |
| Emojis | BehrouzSohrabi/Emoji | Text-based matching for most generic emoji |
| Categories | BehrouzSohrabi/Emoji | Derived from emoji categories (**nouns only**) |

**Note**: The wordbank JSON no longer includes `subcategory`. Categories are only assigned to nouns.

## Emoji Matching

The emoji matcher uses the **BehrouzSohrabi/Emoji** source which includes a `text` field
describing each emoji. This enables finding the most **generic** emoji when multiple match:

### Algorithm

1. Search keywords for the target word
2. If multiple emojis share the keyword, use the `text` field to pick the most generic
3. Prefer shorter/simpler `text` descriptions over compound ones

### Examples

| Word | Matching Emojis | Selected | Reason |
|------|-----------------|----------|--------|
| "not" | 🚫 (prohibited), 🚭 (no smoking), 🚯 (no littering) | 🚫 | "prohibited" is more generic than "no smoking" |
| "one" | 1️⃣ (keycap: 1), 🕐 (one o'clock) | 1️⃣ | Keycap is the canonical representation |
| "new" | 🆕 (NEW button) | 🆕 | Direct match |
| "home" | 🏠 (house) | 🏠 | Direct match |

### Number Words

Number words (one, two, three, etc.) are specially handled to find keycap emojis:
- "one" → 1️⃣
- "two" → 2️⃣
- etc.

## Synonym/Antonym Quality (v3.2.0)

Synonyms and antonyms now use **strict quality filtering** with curated data:

### Quality Modes

- **Strict Mode** (default): Fewer results, higher quality
- **Standard Mode**: More results, may include weaker relationships

### Strong Synonym/Antonym Pairs

The system includes curated lists of verified relationships:

| Word | Strong Synonyms | Strong Antonyms |
|------|-----------------|-----------------|
| "best" | optimal, finest, greatest, supreme, top | worst |
| "good" | fine, excellent, great, pleasant | bad, evil, poor |
| "happy" | joyful, cheerful, glad, pleased | sad, unhappy, miserable |
| "big" | large, huge, enormous, massive | small, little, tiny |

### Weak Relationships (Filtered Out)

These are NOT considered valid synonyms for "best":
- "decent" - adequate, not superlative
- "satisfactory" - acceptable, not exceptional
- "good" - positive but not superlative
- "accomplished" - about skills, not quality ranking

These are NOT considered valid antonyms for "best":
- "evil" - moral term, not quality opposite
- "baddest" - informal/slang
- "poor" - weak contrast with superlative

### Basic Requirements

1. **Must be a single word** - No phrases
2. **Must contain only letters** - No symbols
3. **Must be at least 3 characters**
4. **Must not be obscure** - "entropy", "varlet" filtered out
5. **Must not be the target word**
6. **Must pass semantic check** - Weak relationships filtered

### Source Prioritization

1. **Curated strong pairs** - First priority
2. **API results with high scores** - Added if passing quality check
3. **Source agreement** - When sources agree, higher confidence

## Sentence Requirements

Sentences must meet ALL of these requirements:

1. **Minimum 4 words** - Short phrases are not useful for exercises
2. **Contains EXACT target word** - Not variations (e.g., "run" not "running")
3. **Proper capitalization** - First letter uppercase
4. **Proper punctuation** - Ends with `.`, `!`, or `?`
5. **Single sentence** - Not lists or fragments
6. **Maximum 25 words** - Avoid overly complex sentences

### Two Sentences Per Word

The system aims to provide 2 sentences per word with **varied lengths**:
- One **shorter** sentence (4-8 words) - easier comprehension
- One **longer** sentence (8+ words) - more context

Example for "time":
- Short: "Time stops for nobody."
- Long: "The ebb and flow of time is constant and unchanging."

## Category Assignment

### Nouns Only

Categories are derived from emoji matches and **only assigned to nouns**:
- "home" matches 🏠 → Category: "Travel & Places"
- "book" matches 📚 → Category: "Objects"
- "dog" matches 🐕 → Category: "Animals & Nature"

### Verbs, Adjectives, Adverbs

**Not assigned categories.** The `category` field is omitted from the JSON for non-nouns.

Emoji categories (Smileys & Emotion, Animals & Nature, etc.) are designed 
for concrete objects, not actions or qualities. Assigning them to verbs would be misleading:
- "run" could match 🏃 (People & Body) but running isn't a "person"
- "happy" could match 😊 (Smileys & Emotion) but the word isn't an emoji

For category-based exercises, only use nouns.

## Idiom Management

### Sources

1. **Local idiom files** (primary):
   - `idioms_en.txt` - English idioms
   - `idioms_de.txt` - German idioms
   - `sample_idioms_*.txt` - Sample files (copied on first use)

2. **TheFreeDictionary** (web source, English only):
   - `https://idioms.thefreedictionary.com/{word}`

### File Format

```
# Comments start with #
# One idiom per line

A penny saved is a penny earned
Break a leg
Let the cat out of the bag
```

### Adding Idioms

You can add idioms in several ways:

1. **Edit the file directly**: Add idioms to `idioms_{language}.txt`

2. **API endpoint**: 
   ```
   POST /api/idioms/add
   {"idiom": "New idiom here", "language": "en"}
   ```

3. **Batch update**: After editing the file, update all entries:
   ```
   POST /api/idioms/batch-update
   {"file": "wordbank_en.json", "language": "en"}
   ```

## API Endpoints

### API Status Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Get status of all APIs (Wordnik, Free Dictionary, Datamuse) |
| `/api/status/wordnik` | GET | Detailed Wordnik status with rate limits |
| `/api/generate/set-mode` | POST | Change data source mode during generation |

### Master Wordbank Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/master/status` | GET | Get master wordbank entry count and approved IDs |
| `/api/master/approve` | POST | Add entry to master wordbank |
| `/api/master/remove` | POST | Remove entry from master wordbank |
| `/api/master/list` | GET | List all approved entries with metadata |
| `/api/master/import` | POST | Import entries from wordbank to master |
| `/api/master/get/<id>` | GET | Get specific entry from master |

### Idiom Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/idioms/search` | GET | Search for idioms containing a word |
| `/api/idioms/add` | POST | Add an idiom to the file |
| `/api/idioms/reload` | POST | Reload idiom file after edits |
| `/api/idioms/update-entry` | POST | Update idioms for one entry |
| `/api/idioms/batch-update` | POST | Update idioms for all entries |

### Other Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/emoji/search` | GET | Search for emojis |
| `/api/sound-group` | GET | Get sound group for a word |
| `/api/distractors` | POST | Generate distractors |
| `/api/entry/save` | POST | Save an entry |
| `/api/entry/delete` | POST | Delete an entry |

## File Structure

```
WordbankGenerator/
├── data/
│   ├── wordbank_en.json        # English wordbank
│   ├── wordbank_de.json        # German wordbank
│   ├── master_wordbank_en.json # Master wordbank (approved entries)
│   ├── master_wordbank_de.json # Master wordbank (German)
│   └── cache/                  # API response cache
├── idioms_en.txt               # English idioms (create from sample)
├── idioms_de.txt               # German idioms (create from sample)
├── sample_idioms_en.txt        # Sample English idioms
├── sample_idioms_de.txt        # Sample German idioms
└── ...
```

## Master Wordbank

The master wordbank stores **approved entries** that should not be regenerated.

### When to Approve

Approve an entry when:
- You've manually verified the synonyms/antonyms are accurate
- You've fixed incorrect data from the API
- The entry is complete and high-quality
- You don't want this entry regenerated

### Protected Fields

By default, these fields are protected in approved entries:
- `synonyms`
- `antonyms`
- `definition`
- `emoji`
- `sentences`

### Master Wordbank Format

```json
{
  "version": "1.0",
  "language": "en",
  "lastUpdated": "2024-01-15T10:30:00",
  "totalEntries": 25,
  "entries": {
    "best": {
      "entry": { /* full entry data */ },
      "approvedAt": "2024-01-15T10:30:00",
      "approvedBy": "curator",
      "notes": "Manually verified synonyms/antonyms",
      "protectedFields": ["synonyms", "antonyms", "definition"]
    }
  }
}
```

### Workflow

1. **Generate** wordbank with auto-fetched data
2. **Review** entries in Edit tab
3. **Fix** any incorrect synonyms/antonyms
4. **Approve** high-quality entries (⭐ button)
5. **Regenerate** - approved entries preserved

## Expected Behavior

Because the system prioritizes quality over quantity:

1. **Many words will not get emojis** - Only words with clear emoji matches
2. **Some words may have fewer synonyms** - Invalid ones are filtered out
3. **Some words may have no sentences** - If no valid sentences contain the exact word
4. **Entries may need manual review** - The system marks incomplete entries for review

This is by design. Manual curation is expected for a high-quality wordbank.

## Best Practices

1. **Review all generated entries** - Auto-generation will leave some fields empty
2. **Use curated idiom files** - Build up language-specific idiom collections
3. **Accept empty fields** - Better than incorrect data
4. **Use the edit interface** - Manually add emojis, sentences, etc. where needed
5. **Test with patients** - The ultimate validation is clinical use
6. **Clear cache when updating sources** - Delete `data/cache/` after code changes

### New Best Practices (v3.2.0)

7. **Approve high-quality entries** - Use ⭐ button to protect curated data
8. **Check API status before large generations** - Avoid rate limit surprises
9. **Use overnight mode for large batches** - Best quality, respects rate limits
10. **Review synonyms carefully** - The "strict" filter helps but isn't perfect
11. **Add notes when approving** - Document why entries were approved
12. **Keep master wordbank backed up** - This is your curated data

## Handling Rate Limits

When Wordnik rate limits are hit:

### Option 1: Wait
The UI shows how long until the rate limit resets. Wait and continue.

### Option 2: Overnight Mode
For large wordbanks (100+ words):
1. Enable "Overnight Mode" 
2. Start generation before sleep
3. Processing runs slowly (40s between requests)
4. Stays within rate limits
5. Best quality data

### Option 3: Free Dictionary
Switch to Free Dictionary mode:
- Faster processing
- No rate limits
- Standard quality (less curated synonyms)

## Troubleshooting

### "Wordnik API key is invalid"
- Check your `WORDNIK_API_KEY` environment variable
- Get a new key from wordnik.com
- Or use Free Dictionary mode

### "Rate limit exceeded"
- Wait for reset (shown in UI)
- Or switch modes (see above)

### "Entry not in master wordbank"
- Entry hasn't been approved yet
- Approve in Edit tab after verification

### "Weak synonyms in output"
- Enable "strict" quality mode
- Review and fix manually
- Approve entry to protect fixes

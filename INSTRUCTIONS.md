# WordBank Generator - Instructions

## Overview

The WordBank Generator creates carefully curated word data for aphasia recovery exercises. 
Data quality is paramount - incorrect data can confuse and frustrate patients.

## Key Principles

### NO FALLBACKS - Quality Over Quantity

If data cannot be properly fetched, fields are left empty and entries are marked for review. 
It's better to have incomplete data than incorrect data.

### NO HARDCODED VALUES - Purely Algorithmic

The system relies **entirely** on external data sources. There are no:
- Hardcoded word-to-emoji mappings
- Hardcoded POS patterns
- Hardcoded domain filters
- Hardcoded phrase databases

All matching and filtering is done algorithmically based on the source data.

### Data Sources

| Data Type | Source | Method |
|-----------|--------|--------|
| Definitions | Wordnik, Free Dictionary | First valid definition from API |
| POS | Wordnik, Free Dictionary | As reported by dictionary |
| Synonyms/Antonyms | Wordnik, Free Dictionary, Datamuse | **2+ source overlap required** |
| Sentences | Dictionary examples, Tatoeba | Exact word match, 4+ words |
| Idioms | Local files, TheFreeDictionary | File search + web scraping |
| Emojis | emojilib, emoji-data | Primary keyword match only |

## Emoji Matching

The emoji matcher uses a **purely algorithmic** approach:

1. Search emojilib keyword index for the target word
2. Only accept matches where the word is the **PRIMARY keyword** (position 0)
3. If no primary match exists, return empty string

This means:
- Common words may not get emojis if they're not primary for any emoji
- Abstract words typically won't match
- This is intentional - we prefer no emoji to a wrong emoji

## Sentence Requirements

Sentences must meet ALL of these requirements:

1. **Minimum 4 words** - Short phrases are not useful for exercises
2. **Contains EXACT target word** - Not variations (e.g., "run" not "running")
3. **Proper capitalization** - First letter uppercase
4. **Proper punctuation** - Ends with `.`, `!`, or `?`
5. **Single sentence** - Not lists or fragments

## Synonym/Antonym Validation

Synonyms and antonyms are **only accepted if they appear in 2+ independent sources**:
- Wordnik API
- Free Dictionary API  
- Datamuse API

This prevents incorrect word relationships that could confuse patients.
If fewer than 2 sources agree, the field is left empty.

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

### Parallel Workflow

The idiom system supports parallel editing:
- One person can edit word entries
- Another person can collect and curate idioms
- Idioms can be batch-updated at any time

## API Endpoints

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
│   ├── wordbank_en.json    # English wordbank
│   ├── wordbank_de.json    # German wordbank
│   └── cache/              # API response cache
├── idioms_en.txt           # English idioms (create from sample)
├── idioms_de.txt           # German idioms (create from sample)
├── sample_idioms_en.txt    # Sample English idioms
├── sample_idioms_de.txt    # Sample German idioms
└── ...
```

## Expected Behavior

Because the system is purely algorithmic with no hardcoded values:

1. **Many words will not get emojis** - Only words that are the primary meaning of an emoji will match
2. **Some words may have empty synonyms/antonyms** - If sources don't agree, fields stay empty
3. **Some words may have no sentences** - If no valid sentences contain the exact word
4. **Entries may need manual review** - The system marks incomplete entries for review

This is by design. Manual curation is expected for a high-quality wordbank.

## Best Practices

1. **Review all generated entries** - Auto-generation will leave many fields empty
2. **Use curated idiom files** - Build up language-specific idiom collections
3. **Accept empty fields** - Better than incorrect data
4. **Use the edit interface** - Manually add emojis, sentences, etc. where needed
5. **Test with patients** - The ultimate validation is clinical use

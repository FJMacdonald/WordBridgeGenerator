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
- Hardcoded phrase databases

All matching and filtering is done algorithmically based on the source data.

### Data Sources

| Data Type | Source | Method |
|-----------|--------|--------|
| Definitions | Wordnik, Free Dictionary | First valid definition from API |
| POS | Wordnik, Free Dictionary | As reported by dictionary |
| Synonyms/Antonyms | Wordnik, Free Dictionary, Datamuse | Validated single words only |
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

## Synonym/Antonym Validation

Synonyms and antonyms are **strictly validated** to ensure they are helpful for aphasia patients:

### Requirements

1. **Must be a single word** - No phrases like "look for" or "not available"
2. **Must contain only letters** - No symbols like "!", "~", "¬", "ˈ"
3. **Must be at least 3 characters**
4. **Must not be obscure** - Words like "entropy", "varlet" are filtered out
5. **Must not be the target word**

### Bad Synonyms (Filtered Out)

| Word | Bad Synonym | Reason |
|------|-------------|--------|
| "not" | "!" | Symbol, not a word |
| "not" | "¬" | Symbol, not a word |
| "not" | "ˈ" | Symbol, not a word |
| "information" | "entropy" | Technical term, confusing |
| "page" | "varlet" | Archaic, obscure |
| "free" | "befree" | Not standard English |

### Source Agreement

When multiple sources (Wordnik, Free Dictionary, Datamuse) agree on a synonym,
it is prioritized. Single-source synonyms are used but limited.

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

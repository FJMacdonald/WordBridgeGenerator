"""
Master wordbank manager for approved/curated entries.

The master wordbank contains entries that have been manually reviewed
and approved. These entries should not be overwritten during generation.

Features:
- Stores approved entries in a separate master file
- Prevents regeneration of approved words
- Allows merging master entries into generated wordbanks
- Tracks approval status and curator notes
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set

from ..config import DATA_DIR


class MasterWordbank:
    """
    Manages the master wordbank of approved entries.
    
    The master wordbank is a curated collection of high-quality
    word entries that have been manually reviewed and approved.
    These entries take precedence over auto-generated data.
    
    File format:
    {
        "version": "1.0",
        "language": "en",
        "lastUpdated": "ISO timestamp",
        "entries": {
            "word_id": {
                "entry": { ... full entry data ... },
                "approvedAt": "ISO timestamp",
                "approvedBy": "curator name",
                "notes": "optional curator notes",
                "protectedFields": ["synonyms", "antonyms", ...]
            }
        }
    }
    """
    
    DEFAULT_FILENAME = "master_wordbank_{lang}.json"
    
    def __init__(self, language: str = "en"):
        """
        Initialize master wordbank for a language.
        
        Args:
            language: Language code (e.g., 'en', 'de')
        """
        self.language = language
        self.filepath = DATA_DIR / self.DEFAULT_FILENAME.format(lang=language)
        self.data = self._default_data()
        self._load()
    
    def _default_data(self) -> Dict:
        """Get default master wordbank structure."""
        return {
            "version": "1.0",
            "language": self.language,
            "lastUpdated": datetime.now().isoformat(),
            "totalEntries": 0,
            "entries": {},
        }
    
    def _load(self) -> bool:
        """Load master wordbank from file."""
        if not self.filepath.exists():
            return False
        
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            return True
        except (IOError, json.JSONDecodeError) as e:
            print(f"⚠ Error loading master wordbank: {e}")
            self.data = self._default_data()
            return False
    
    def save(self) -> bool:
        """Save master wordbank to file."""
        self.data['lastUpdated'] = datetime.now().isoformat()
        self.data['totalEntries'] = len(self.data.get('entries', {}))
        
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"⚠ Error saving master wordbank: {e}")
            return False
    
    def approve_entry(self, entry: Dict, 
                     approved_by: str = "curator",
                     notes: str = "",
                     protected_fields: List[str] = None) -> bool:
        """
        Add or update an approved entry in the master wordbank.
        
        Args:
            entry: Full entry dictionary
            approved_by: Name of the curator
            notes: Optional notes about the entry
            protected_fields: List of fields that should not be overwritten
                             If None, all fields are protected
        
        Returns:
            True if successful
        """
        entry_id = entry.get('id')
        if not entry_id:
            return False
        
        # Default protected fields - the key relationship data
        if protected_fields is None:
            protected_fields = [
                'synonyms', 'antonyms', 'definition', 
                'partOfSpeech', 'emoji', 'sentences'
            ]
        
        self.data['entries'][entry_id] = {
            'entry': entry,
            'approvedAt': datetime.now().isoformat(),
            'approvedBy': approved_by,
            'notes': notes,
            'protectedFields': protected_fields,
        }
        
        return self.save()
    
    def remove_entry(self, entry_id: str) -> bool:
        """
        Remove an entry from the master wordbank.
        
        Args:
            entry_id: ID of entry to remove
            
        Returns:
            True if entry was found and removed
        """
        if entry_id in self.data['entries']:
            del self.data['entries'][entry_id]
            return self.save()
        return False
    
    def get_entry(self, entry_id: str) -> Optional[Dict]:
        """
        Get an approved entry by ID.
        
        Args:
            entry_id: Entry ID to look up
            
        Returns:
            Entry dictionary or None
        """
        master_entry = self.data['entries'].get(entry_id)
        if master_entry:
            return master_entry.get('entry')
        return None
    
    def get_entry_with_metadata(self, entry_id: str) -> Optional[Dict]:
        """
        Get an approved entry with its metadata.
        
        Args:
            entry_id: Entry ID to look up
            
        Returns:
            Full master entry (entry + metadata) or None
        """
        return self.data['entries'].get(entry_id)
    
    def is_approved(self, entry_id: str) -> bool:
        """Check if a word is in the master wordbank."""
        return entry_id in self.data['entries']
    
    def get_protected_fields(self, entry_id: str) -> List[str]:
        """
        Get list of protected fields for an entry.
        
        Args:
            entry_id: Entry ID
            
        Returns:
            List of protected field names
        """
        master_entry = self.data['entries'].get(entry_id)
        if master_entry:
            return master_entry.get('protectedFields', [])
        return []
    
    def get_all_approved_ids(self) -> Set[str]:
        """Get set of all approved entry IDs."""
        return set(self.data['entries'].keys())
    
    def count(self) -> int:
        """Get number of approved entries."""
        return len(self.data.get('entries', {}))
    
    def merge_into_wordbank(self, wordbank_data: Dict) -> Dict:
        """
        Merge master entries into a wordbank.
        
        Master entries take precedence - protected fields from master
        entries will overwrite generated data.
        
        Args:
            wordbank_data: The wordbank dictionary to merge into
            
        Returns:
            Updated wordbank dictionary
        """
        if not wordbank_data.get('words'):
            return wordbank_data
        
        # Build index of wordbank entries
        word_index = {
            entry.get('id'): i 
            for i, entry in enumerate(wordbank_data['words'])
        }
        
        # Merge master entries
        for entry_id, master_entry in self.data['entries'].items():
            approved_entry = master_entry.get('entry', {})
            protected_fields = master_entry.get('protectedFields', [])
            
            if entry_id in word_index:
                # Update existing entry
                idx = word_index[entry_id]
                existing = wordbank_data['words'][idx]
                
                # Merge protected fields from master
                for field in protected_fields:
                    if field in approved_entry:
                        if field in ['synonyms', 'antonyms', 'associated', 'rhymes']:
                            # These are in relationships
                            existing.setdefault('relationships', {})
                            existing['relationships'][field] = approved_entry.get('relationships', {}).get(field, [])
                        elif field == 'emoji':
                            existing.setdefault('visual', {})
                            existing['visual']['emoji'] = approved_entry.get('visual', {}).get('emoji', '')
                        else:
                            existing[field] = approved_entry[field]
                
                # Mark as not needing review since it's approved
                existing['needsReview'] = False
                existing['sources'] = existing.get('sources', {})
                existing['sources']['master'] = 'approved'
            else:
                # Add new entry from master
                wordbank_data['words'].append(approved_entry)
        
        return wordbank_data
    
    def should_skip_generation(self, word: str) -> bool:
        """
        Check if a word should skip generation because it's approved.
        
        Args:
            word: Word to check
            
        Returns:
            True if word is approved and should not be regenerated
        """
        entry_id = word.lower().strip()
        return self.is_approved(entry_id)
    
    def get_merged_entry(self, entry_id: str, generated_entry: Dict) -> Dict:
        """
        Get an entry with master data merged in.
        
        Protected fields from master take precedence.
        
        Args:
            entry_id: Entry ID
            generated_entry: Auto-generated entry data
            
        Returns:
            Merged entry
        """
        master_data = self.get_entry_with_metadata(entry_id)
        if not master_data:
            return generated_entry
        
        approved_entry = master_data.get('entry', {})
        protected_fields = master_data.get('protectedFields', [])
        
        # Start with generated entry
        result = dict(generated_entry)
        
        # Overlay protected fields from master
        for field in protected_fields:
            if field in ['synonyms', 'antonyms', 'associated', 'rhymes']:
                result.setdefault('relationships', {})
                master_rel = approved_entry.get('relationships', {})
                if field in master_rel:
                    result['relationships'][field] = master_rel[field]
            elif field == 'emoji':
                result.setdefault('visual', {})
                master_visual = approved_entry.get('visual', {})
                if 'emoji' in master_visual:
                    result['visual']['emoji'] = master_visual['emoji']
            elif field in approved_entry:
                result[field] = approved_entry[field]
        
        return result
    
    def export_for_review(self) -> List[Dict]:
        """
        Export all entries for review.
        
        Returns:
            List of entries with metadata
        """
        return [
            {
                'id': entry_id,
                'word': entry_data.get('entry', {}).get('word', ''),
                'approvedAt': entry_data.get('approvedAt'),
                'approvedBy': entry_data.get('approvedBy'),
                'notes': entry_data.get('notes'),
                'protectedFields': entry_data.get('protectedFields', []),
            }
            for entry_id, entry_data in self.data['entries'].items()
        ]
    
    def import_from_wordbank(self, wordbank_path: str, 
                            entry_ids: List[str] = None,
                            approved_by: str = "import") -> int:
        """
        Import entries from a wordbank file into master.
        
        Args:
            wordbank_path: Path to wordbank file
            entry_ids: List of entry IDs to import (None = all)
            approved_by: Curator name for imported entries
            
        Returns:
            Number of entries imported
        """
        try:
            with open(wordbank_path, 'r', encoding='utf-8') as f:
                wordbank = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"⚠ Error loading wordbank: {e}")
            return 0
        
        imported = 0
        for entry in wordbank.get('words', []):
            entry_id = entry.get('id')
            if not entry_id:
                continue
            
            # Filter by entry_ids if provided
            if entry_ids and entry_id not in entry_ids:
                continue
            
            self.approve_entry(
                entry=entry,
                approved_by=approved_by,
                notes=f"Imported from {Path(wordbank_path).name}",
            )
            imported += 1
        
        return imported


# Cache for master wordbanks by language
_master_cache: Dict[str, MasterWordbank] = {}


def get_master_wordbank(language: str = "en") -> MasterWordbank:
    """Get or create master wordbank for a language."""
    if language not in _master_cache:
        _master_cache[language] = MasterWordbank(language)
    return _master_cache[language]

"""
Wordbank file manager and data structures.
"""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from ..config import DATA_DIR


@dataclass
class WordEntry:
    """Complete word entry for the wordbank."""
    
    id: str
    word: str
    partOfSpeech: str = "noun"
    category: Any = field(default_factory=list)  # Array of category sources or string for backwards compat
    definition: str = ""
    soundGroup: str = ""
    emoji: str = ""
    imageUrl: str = ""  # For Noun Project or other image sources
    imageAttribution: str = ""  # Required attribution for Noun Project
    synonyms: List[str] = field(default_factory=list)
    antonyms: List[str] = field(default_factory=list)
    associated: List[str] = field(default_factory=list)
    rhymes: List[str] = field(default_factory=list)
    distractors: List[str] = field(default_factory=list)
    sentences: List[str] = field(default_factory=list)
    phrases: List[str] = field(default_factory=list)
    frequencyRank: int = 99999
    needsReview: bool = True
    sources: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        visual = {
            "emoji": self.emoji,
            "asset": None
        }
        
        # Add image info if using Noun Project or other image source
        if self.imageUrl:
            visual["imageUrl"] = self.imageUrl
        if self.imageAttribution:
            visual["attribution"] = self.imageAttribution
        
        result = {
            "id": self.id,
            "word": self.word,
            "partOfSpeech": self.partOfSpeech,
            "definition": self.definition,
            "soundGroup": self.soundGroup,
            "visual": visual,
            "relationships": {
                "synonyms": self.synonyms,
                "antonyms": self.antonyms,
                "associated": self.associated,
                "rhymes": self.rhymes,
            },
            "distractors": self.distractors,
            "sentences": self.sentences,
            "phrases": self.phrases,
            "frequencyRank": self.frequencyRank,
            "needsReview": self.needsReview,
            "sources": self.sources,
        }
        # Include category - now an array of sources or empty list
        # Category can be a list of dicts with source/category, a string (legacy), or empty
        if self.category:
            result["category"] = self.category
        else:
            result["category"] = []
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'WordEntry':
        """Create from dictionary."""
        visual = data.get('visual', {})
        relationships = data.get('relationships', {})
        
        return cls(
            id=data.get('id', ''),
            word=data.get('word', ''),
            partOfSpeech=data.get('partOfSpeech', 'noun'),
            category=data.get('category', ''),
            definition=data.get('definition', ''),
            soundGroup=data.get('soundGroup', ''),
            emoji=visual.get('emoji', '') if isinstance(visual, dict) else '',
            imageUrl=visual.get('imageUrl', '') if isinstance(visual, dict) else '',
            imageAttribution=visual.get('attribution', '') if isinstance(visual, dict) else '',
            synonyms=relationships.get('synonyms', []),
            antonyms=relationships.get('antonyms', []),
            associated=relationships.get('associated', []),
            rhymes=relationships.get('rhymes', []),
            distractors=data.get('distractors', []),
            sentences=data.get('sentences', []),
            phrases=data.get('phrases', []),
            frequencyRank=data.get('frequencyRank', 99999),
            needsReview=data.get('needsReview', True),
            sources=data.get('sources', {}),
        )
    
    def is_complete(self) -> bool:
        """
        Check if entry has all required fields.
        
        Note: Category is only required for nouns.
        An emoji OR image URL satisfies the visual requirement.
        Category can be a list (new format) or string (legacy).
        """
        has_visual = bool(self.emoji) or bool(self.imageUrl)
        
        base_complete = (
            bool(self.word) and
            bool(self.definition) and
            has_visual and
            len(self.sentences) >= 2 and
            len(self.distractors) >= 10
        )
        
        # Category is only required for nouns
        if self.partOfSpeech == 'noun':
            # Handle category as list or string
            has_category = bool(self.category) if isinstance(self.category, str) else len(self.category) > 0
            return base_complete and has_category
        
        return base_complete


class WordbankManager:
    """
    Manages wordbank JSON files.
    """
    
    def __init__(self, filepath: str = None):
        """
        Initialize wordbank manager.
        
        Args:
            filepath: Path to wordbank file (created if doesn't exist)
        """
        if filepath:
            self.filepath = Path(filepath)
        else:
            self.filepath = None
        
        self.data = self._default_data()
        self.entries_by_id: Dict[str, Dict] = {}
        
        if self.filepath and self.filepath.exists():
            self.load()
    
    def _default_data(self) -> Dict:
        """Get default wordbank structure."""
        return {
            "version": "2.0",
            "language": "en",
            "generatedAt": datetime.now().isoformat(),
            "generationMethod": "web_app",
            "totalEntries": 0,
            "words": [],
        }
    
    def load(self) -> bool:
        """Load wordbank from file."""
        if not self.filepath or not self.filepath.exists():
            return False
        
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            
            # Build index
            self.entries_by_id = {}
            for entry in self.data.get('words', []):
                entry_id = entry.get('id', '')
                if entry_id:
                    self.entries_by_id[entry_id] = entry
            
            return True
            
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error loading {self.filepath}: {e}")
            self.data = self._default_data()
            return False
    
    def save(self) -> bool:
        """Save wordbank to file."""
        if not self.filepath:
            return False
        
        # Ensure directory exists
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Update total entries
        self.data['totalEntries'] = len(self.data.get('words', []))
        
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            return True
            
        except IOError as e:
            print(f"Error saving {self.filepath}: {e}")
            return False
    
    def add_entry(self, entry: WordEntry) -> bool:
        """
        Add or update an entry.
        
        Args:
            entry: WordEntry to add
            
        Returns:
            True if successful
        """
        entry_dict = entry.to_dict()
        
        if entry.id in self.entries_by_id:
            # Update existing
            for i, e in enumerate(self.data['words']):
                if e.get('id') == entry.id:
                    self.data['words'][i] = entry_dict
                    break
        else:
            # Add new
            self.data['words'].append(entry_dict)
        
        self.entries_by_id[entry.id] = entry_dict
        self.data['totalEntries'] = len(self.data['words'])
        
        return True
    
    def get_entry(self, entry_id: str) -> Optional[Dict]:
        """Get entry by ID."""
        return self.entries_by_id.get(entry_id)
    
    def get_entry_as_object(self, entry_id: str) -> Optional[WordEntry]:
        """Get entry as WordEntry object."""
        data = self.get_entry(entry_id)
        return WordEntry.from_dict(data) if data else None
    
    def get_entry_by_index(self, index: int) -> Optional[Dict]:
        """Get entry by index."""
        words = self.data.get('words', [])
        if 0 <= index < len(words):
            return words[index]
        return None
    
    def delete_entry(self, entry_id: str) -> bool:
        """Delete an entry by ID."""
        if entry_id not in self.entries_by_id:
            return False
        
        del self.entries_by_id[entry_id]
        self.data['words'] = [
            e for e in self.data['words'] 
            if e.get('id') != entry_id
        ]
        self.data['totalEntries'] = len(self.data['words'])
        
        return True
    
    def count(self) -> int:
        """Get entry count."""
        return len(self.data.get('words', []))
    
    def get_language(self) -> str:
        """Get wordbank language."""
        return self.data.get('language', 'en')
    
    def set_language(self, language: str):
        """Set wordbank language."""
        self.data['language'] = language
    
    def get_all_words(self) -> List[str]:
        """Get list of all words in wordbank."""
        return [e.get('word', '') for e in self.data.get('words', [])]
    
    def get_incomplete_entries(self) -> List[Dict]:
        """Get entries that need review."""
        return [
            e for e in self.data.get('words', [])
            if e.get('needsReview', True)
        ]
    
    def search(self, query: str) -> List[Dict]:
        """Search entries by word."""
        query_lower = query.lower()
        return [
            e for e in self.data.get('words', [])
            if query_lower in e.get('word', '').lower()
        ]
    
    @staticmethod
    def list_files() -> List[Dict]:
        """List all wordbank files in data directory."""
        files = []
        
        for path in DATA_DIR.glob('*.json'):
            if path.name == 'session_state.json':
                continue
            
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                files.append({
                    'name': path.name,
                    'path': str(path),
                    'entries': data.get('totalEntries', len(data.get('words', []))),
                    'language': data.get('language', 'en'),
                    'version': data.get('version', '1.0'),
                })
            except:
                pass
        
        return sorted(files, key=lambda x: x['name'])

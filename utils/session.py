"""
Session state management for batch processing.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Any, Optional

from ..config import SESSION_FILE


@dataclass
class SessionState:
    """Tracks batch processing state for resumption."""
    
    mode: str = ""  # "generate", "edit", "translate"
    current_file: str = ""
    reference_file: str = ""
    current_index: int = 0
    total_items: int = 0
    completed_ids: List[str] = field(default_factory=list)
    pending_words: List[str] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)
    last_updated: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SessionState':
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def save(self) -> bool:
        """Save session state to file."""
        self.last_updated = datetime.now().isoformat()
        
        try:
            with open(SESSION_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2)
            return True
        except IOError:
            return False
    
    @classmethod
    def load(cls) -> Optional['SessionState']:
        """Load session state from file."""
        if not SESSION_FILE.exists():
            return None
        
        try:
            with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (IOError, json.JSONDecodeError):
            return None
    
    @classmethod
    def clear(cls) -> bool:
        """Clear session state file."""
        try:
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
            return True
        except IOError:
            return False
    
    def mark_complete(self, entry_id: str):
        """Mark an entry as completed."""
        if entry_id not in self.completed_ids:
            self.completed_ids.append(entry_id)
        self.current_index += 1
        self.save()
    
    def is_complete(self, entry_id: str) -> bool:
        """Check if an entry is completed."""
        return entry_id in self.completed_ids
    
    @property
    def progress_percent(self) -> float:
        """Get progress as percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.current_index / self.total_items) * 100

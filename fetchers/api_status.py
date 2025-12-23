"""
API status tracking and rate limit handling.

Provides:
- Authentication status checking for Merriam-Webster APIs
- Rate limit tracking and reporting
- User-friendly error messages
- Save/resume support for rate-limited scenarios
"""

import os
import time
import json
import requests
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from ..config import (
    URLS, MERRIAM_WEBSTER_LEARNERS_KEY, MERRIAM_WEBSTER_THESAURUS_KEY,
    NOUN_PROJECT_KEY, RATE_LIMITS, PROGRESS_FILE
)


class APIStatus(Enum):
    """Status of an API connection."""
    OK = "ok"
    AUTH_ERROR = "auth_error"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


@dataclass
class RateLimitInfo:
    """Information about API rate limits."""
    requests_per_minute: int = 0
    requests_per_day: int = 0
    requests_remaining_minute: int = 0
    requests_remaining_day: int = 0
    reset_time_minute: Optional[datetime] = None
    reset_time_day: Optional[datetime] = None
    last_checked: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'requests_per_minute': self.requests_per_minute,
            'requests_per_day': self.requests_per_day,
            'requests_remaining_minute': self.requests_remaining_minute,
            'requests_remaining_day': self.requests_remaining_day,
            'reset_time_minute': self.reset_time_minute.isoformat() if self.reset_time_minute else None,
            'reset_time_day': self.reset_time_day.isoformat() if self.reset_time_day else None,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
        }
    
    def is_rate_limited(self) -> bool:
        """Check if currently rate limited."""
        return self.requests_remaining_minute <= 0 or self.requests_remaining_day <= 0
    
    def wait_time_seconds(self) -> int:
        """Get seconds to wait before next request is allowed."""
        now = datetime.now()
        
        if self.requests_remaining_minute <= 0 and self.reset_time_minute:
            minute_wait = (self.reset_time_minute - now).total_seconds()
            if minute_wait > 0:
                return int(minute_wait) + 1
        
        if self.requests_remaining_day <= 0 and self.reset_time_day:
            day_wait = (self.reset_time_day - now).total_seconds()
            if day_wait > 0:
                return int(day_wait) + 1
        
        return 0
    
    def format_wait_time(self) -> str:
        """Get human-readable wait time."""
        seconds = self.wait_time_seconds()
        if seconds <= 0:
            return "Ready"
        elif seconds < 60:
            return f"{seconds} seconds"
        elif seconds < 3600:
            return f"{seconds // 60} minutes"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"


@dataclass
class APIStatusInfo:
    """Complete status information for an API."""
    name: str
    status: APIStatus
    message: str = ""
    rate_limits: Optional[RateLimitInfo] = None
    last_error: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'name': self.name,
            'status': self.status.value,
            'message': self.message,
            'rate_limits': self.rate_limits.to_dict() if self.rate_limits else None,
            'last_error': self.last_error,
        }


class ProgressSaver:
    """
    Saves and restores generation progress for rate limit recovery.
    
    When rate limits are encountered, this allows saving current progress
    and resuming later when limits reset.
    """
    
    def __init__(self, progress_file: Path = PROGRESS_FILE):
        self.progress_file = progress_file
    
    def save_progress(self, progress_data: Dict) -> bool:
        """
        Save current generation progress.
        
        Args:
            progress_data: Dict containing:
                - words_completed: List of words already processed
                - words_remaining: List of words still to process
                - current_wordbank: Path to current wordbank file
                - settings: Generation settings
                - rate_limit_info: Info about which API was rate limited
                - timestamp: When progress was saved
                
        Returns:
            True if saved successfully
        """
        try:
            progress_data['timestamp'] = datetime.now().isoformat()
            
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error saving progress: {e}")
            return False
    
    def load_progress(self) -> Optional[Dict]:
        """
        Load saved progress.
        
        Returns:
            Progress data dict, or None if no saved progress
        """
        if not self.progress_file.exists():
            return None
        
        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading progress: {e}")
            return None
    
    def clear_progress(self) -> bool:
        """Clear saved progress (after successful completion)."""
        try:
            if self.progress_file.exists():
                self.progress_file.unlink()
            return True
        except Exception as e:
            print(f"Error clearing progress: {e}")
            return False
    
    def has_saved_progress(self) -> bool:
        """Check if there's saved progress."""
        return self.progress_file.exists()


class APIStatusTracker:
    """
    Tracks API status and rate limits.
    
    Provides centralized tracking of:
    - Merriam-Webster Learner's Dictionary
    - Merriam-Webster Intermediate Thesaurus
    - The Noun Project
    - Free Dictionary
    - Datamuse
    """
    
    def __init__(self):
        self._status_cache: Dict[str, APIStatusInfo] = {}
        self._request_times: Dict[str, list] = {
            'mw_learners': [],
            'mw_thesaurus': [],
            'noun_project': [],
        }
        self._rate_limits: Dict[str, RateLimitInfo] = {}
        self._progress_saver = ProgressSaver()
    
    def check_mw_learners_auth(self) -> APIStatusInfo:
        """Check Merriam-Webster Learner's Dictionary API status."""
        if not MERRIAM_WEBSTER_LEARNERS_KEY:
            return APIStatusInfo(
                name="MW Learner's Dictionary",
                status=APIStatus.NOT_CONFIGURED,
                message="MW Learner's API key not configured. Set MW_LEARNERS_API_KEY.",
            )
        
        try:
            url = f"{URLS['mw_learners']}/test"
            params = {'key': MERRIAM_WEBSTER_LEARNERS_KEY}
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                rate_info = self._create_rate_info('merriam_webster')
                self._rate_limits['mw_learners'] = rate_info
                
                return APIStatusInfo(
                    name="MW Learner's Dictionary",
                    status=APIStatus.OK,
                    message="MW Learner's Dictionary API connected.",
                    rate_limits=rate_info,
                )
            
            elif resp.status_code in [401, 403]:
                return APIStatusInfo(
                    name="MW Learner's Dictionary",
                    status=APIStatus.AUTH_ERROR,
                    message="MW API key is invalid.",
                    last_error=f"HTTP {resp.status_code}",
                )
            
            elif resp.status_code == 429:
                rate_info = self._create_rate_info('merriam_webster')
                rate_info.requests_remaining_minute = 0
                self._rate_limits['mw_learners'] = rate_info
                
                return APIStatusInfo(
                    name="MW Learner's Dictionary",
                    status=APIStatus.RATE_LIMITED,
                    message=f"Rate limited. Wait {rate_info.format_wait_time()}.",
                    rate_limits=rate_info,
                    last_error="429 Too Many Requests",
                )
            
            else:
                return APIStatusInfo(
                    name="MW Learner's Dictionary",
                    status=APIStatus.UNAVAILABLE,
                    message=f"Unexpected status: {resp.status_code}",
                    last_error=f"HTTP {resp.status_code}",
                )
                
        except requests.exceptions.Timeout:
            return APIStatusInfo(
                name="MW Learner's Dictionary",
                status=APIStatus.UNAVAILABLE,
                message="Request timed out.",
                last_error="Timeout",
            )
        except Exception as e:
            return APIStatusInfo(
                name="MW Learner's Dictionary",
                status=APIStatus.UNAVAILABLE,
                message=f"Error: {str(e)}",
                last_error=str(e),
            )
    
    def check_mw_thesaurus_auth(self) -> APIStatusInfo:
        """Check Merriam-Webster Thesaurus API status."""
        if not MERRIAM_WEBSTER_THESAURUS_KEY:
            return APIStatusInfo(
                name="MW Thesaurus",
                status=APIStatus.NOT_CONFIGURED,
                message="MW Thesaurus API key not configured. Set MW_THESAURUS_API_KEY.",
            )
        
        try:
            url = f"{URLS['mw_thesaurus']}/test"
            params = {'key': MERRIAM_WEBSTER_THESAURUS_KEY}
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                rate_info = self._create_rate_info('merriam_webster')
                self._rate_limits['mw_thesaurus'] = rate_info
                
                return APIStatusInfo(
                    name="MW Thesaurus",
                    status=APIStatus.OK,
                    message="MW Thesaurus API connected.",
                    rate_limits=rate_info,
                )
            
            elif resp.status_code in [401, 403]:
                return APIStatusInfo(
                    name="MW Thesaurus",
                    status=APIStatus.AUTH_ERROR,
                    message="MW Thesaurus API key is invalid.",
                    last_error=f"HTTP {resp.status_code}",
                )
            
            elif resp.status_code == 429:
                rate_info = self._create_rate_info('merriam_webster')
                rate_info.requests_remaining_minute = 0
                
                return APIStatusInfo(
                    name="MW Thesaurus",
                    status=APIStatus.RATE_LIMITED,
                    message="Rate limited.",
                    rate_limits=rate_info,
                )
            
            else:
                return APIStatusInfo(
                    name="MW Thesaurus",
                    status=APIStatus.UNAVAILABLE,
                    message=f"Status: {resp.status_code}",
                )
                
        except Exception as e:
            return APIStatusInfo(
                name="MW Thesaurus",
                status=APIStatus.UNAVAILABLE,
                message=f"Error: {str(e)}",
            )
    
    def _create_rate_info(self, api_name: str) -> RateLimitInfo:
        """Create rate limit info for an API."""
        now = datetime.now()
        limits = RATE_LIMITS.get(api_name, {})
        
        return RateLimitInfo(
            requests_per_minute=limits.get('requests_per_minute', 30),
            requests_per_day=limits.get('requests_per_day', 1000),
            requests_remaining_minute=limits.get('requests_per_minute', 30),
            requests_remaining_day=limits.get('requests_per_day', 1000),
            reset_time_minute=now + timedelta(minutes=1),
            reset_time_day=now.replace(hour=0, minute=0, second=0) + timedelta(days=1),
            last_checked=now,
        )
    
    def check_free_dictionary(self) -> APIStatusInfo:
        """Check Free Dictionary API availability."""
        try:
            url = f"{URLS['free_dictionary']}/test"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code in [200, 404]:
                return APIStatusInfo(
                    name="Free Dictionary",
                    status=APIStatus.OK,
                    message="Free Dictionary API is available (no rate limits).",
                )
            else:
                return APIStatusInfo(
                    name="Free Dictionary",
                    status=APIStatus.UNAVAILABLE,
                    message=f"Status {resp.status_code}",
                )
                
        except Exception as e:
            return APIStatusInfo(
                name="Free Dictionary",
                status=APIStatus.UNAVAILABLE,
                message=f"Error: {str(e)}",
            )
    
    def check_datamuse(self) -> APIStatusInfo:
        """Check Datamuse API availability."""
        try:
            url = f"{URLS['datamuse']}?rel_rhy=test&max=1"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code == 200:
                return APIStatusInfo(
                    name="Datamuse",
                    status=APIStatus.OK,
                    message="Datamuse API is available (no rate limits).",
                )
            else:
                return APIStatusInfo(
                    name="Datamuse",
                    status=APIStatus.UNAVAILABLE,
                    message=f"Status {resp.status_code}",
                )
                
        except Exception as e:
            return APIStatusInfo(
                name="Datamuse",
                status=APIStatus.UNAVAILABLE,
                message=f"Error: {str(e)}",
            )
    
    def check_all_apis(self) -> Dict[str, APIStatusInfo]:
        """Check status of all APIs."""
        return {
            'mw_learners': self.check_mw_learners_auth(),
            'mw_thesaurus': self.check_mw_thesaurus_auth(),
            'free_dictionary': self.check_free_dictionary(),
            'datamuse': self.check_datamuse(),
        }
    
    def get_recommended_mode(self) -> Dict:
        """Get recommended generation mode based on API status."""
        mw_status = self.check_mw_learners_auth()
        
        if mw_status.status == APIStatus.OK:
            return {
                'mode': 'mw_preferred',
                'quality': 'high',
                'message': 'Using Merriam-Webster APIs for highest quality data.',
                'rate_limits': mw_status.rate_limits.to_dict() if mw_status.rate_limits else None,
            }
        
        elif mw_status.status == APIStatus.RATE_LIMITED:
            wait_time = mw_status.rate_limits.wait_time_seconds() if mw_status.rate_limits else 0
            
            return {
                'mode': 'rate_limited',
                'quality': 'pending',
                'message': f'MW rate limited. Wait {mw_status.rate_limits.format_wait_time()} or use Free Dictionary.',
                'wait_seconds': wait_time,
                'rate_limits': mw_status.rate_limits.to_dict() if mw_status.rate_limits else None,
                'options': [
                    {
                        'id': 'wait',
                        'label': f'Wait {mw_status.rate_limits.format_wait_time()}',
                        'description': 'Wait for rate limit to reset.',
                    },
                    {
                        'id': 'save_resume',
                        'label': 'Save & Resume Later',
                        'description': 'Save progress and resume when limits reset.',
                    },
                    {
                        'id': 'free_dictionary',
                        'label': 'Use Free Dictionary',
                        'description': 'Continue with Free Dictionary (lower quality).',
                    },
                ],
            }
        
        elif mw_status.status == APIStatus.NOT_CONFIGURED:
            return {
                'mode': 'free_dictionary',
                'quality': 'standard',
                'message': 'MW not configured. Using Free Dictionary.',
                'hint': 'Set MW_LEARNERS_API_KEY and MW_THESAURUS_API_KEY for higher quality.',
            }
        
        else:
            return {
                'mode': 'free_dictionary',
                'quality': 'standard',
                'message': f'MW unavailable ({mw_status.message}). Using Free Dictionary.',
                'error': mw_status.last_error,
            }
    
    def save_progress(self, progress_data: Dict) -> bool:
        """Save generation progress for later resumption."""
        return self._progress_saver.save_progress(progress_data)
    
    def load_progress(self) -> Optional[Dict]:
        """Load saved progress."""
        return self._progress_saver.load_progress()
    
    def clear_progress(self) -> bool:
        """Clear saved progress."""
        return self._progress_saver.clear_progress()
    
    def has_saved_progress(self) -> bool:
        """Check if there's saved progress to resume."""
        return self._progress_saver.has_saved_progress()


# Global tracker instance
_api_tracker: Optional[APIStatusTracker] = None


def get_api_tracker() -> APIStatusTracker:
    """Get or create the global API status tracker."""
    global _api_tracker
    if _api_tracker is None:
        _api_tracker = APIStatusTracker()
    return _api_tracker

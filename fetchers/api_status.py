"""
API status tracking and rate limit handling.

Provides:
- Authentication status checking for Wordnik
- Rate limit tracking and reporting
- User-friendly error messages
- Overnight mode support for rate-limited APIs
"""

import os
import time
import requests
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from ..config import URLS, WORDNIK_API_KEY


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
    requests_per_hour: int = 0
    requests_remaining_minute: int = 0
    requests_remaining_hour: int = 0
    reset_time_minute: Optional[datetime] = None
    reset_time_hour: Optional[datetime] = None
    last_checked: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'requests_per_minute': self.requests_per_minute,
            'requests_per_hour': self.requests_per_hour,
            'requests_remaining_minute': self.requests_remaining_minute,
            'requests_remaining_hour': self.requests_remaining_hour,
            'reset_time_minute': self.reset_time_minute.isoformat() if self.reset_time_minute else None,
            'reset_time_hour': self.reset_time_hour.isoformat() if self.reset_time_hour else None,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
        }
    
    def is_rate_limited(self) -> bool:
        """Check if currently rate limited."""
        return self.requests_remaining_minute <= 0 or self.requests_remaining_hour <= 0
    
    def wait_time_seconds(self) -> int:
        """Get seconds to wait before next request is allowed."""
        now = datetime.now()
        
        if self.requests_remaining_minute <= 0 and self.reset_time_minute:
            minute_wait = (self.reset_time_minute - now).total_seconds()
            if minute_wait > 0:
                return int(minute_wait) + 1
        
        if self.requests_remaining_hour <= 0 and self.reset_time_hour:
            hour_wait = (self.reset_time_hour - now).total_seconds()
            if hour_wait > 0:
                return int(hour_wait) + 1
        
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


class APIStatusTracker:
    """
    Tracks API status and rate limits.
    
    Provides centralized tracking of:
    - Wordnik API authentication and rate limits
    - Free Dictionary availability
    - Datamuse availability
    """
    
    # Wordnik rate limits (from their documentation)
    # Free tier: 100 requests/hour, 15,000 requests/day
    # These are estimates; actual limits may vary
    WORDNIK_LIMITS = {
        'requests_per_minute': 15,  # ~100/hour = ~1.67/min, but allow bursts
        'requests_per_hour': 100,
    }
    
    def __init__(self):
        self._status_cache: Dict[str, APIStatusInfo] = {}
        self._request_times: Dict[str, list] = {
            'wordnik': [],
        }
        self._rate_limits: Dict[str, RateLimitInfo] = {}
    
    def check_wordnik_auth(self) -> APIStatusInfo:
        """
        Check Wordnik API authentication status.
        
        Returns:
            APIStatusInfo with auth status and any error messages
        """
        if not WORDNIK_API_KEY:
            return APIStatusInfo(
                name="Wordnik",
                status=APIStatus.NOT_CONFIGURED,
                message="Wordnik API key not configured. Set WORDNIK_API_KEY environment variable for higher quality data.",
            )
        
        try:
            # Test with a simple word lookup
            url = f"{URLS['wordnik']}/test/definitions"
            params = {
                'limit': 1,
                'api_key': WORDNIK_API_KEY,
            }
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                # Check rate limit headers
                rate_info = self._parse_wordnik_headers(resp.headers)
                self._rate_limits['wordnik'] = rate_info
                
                return APIStatusInfo(
                    name="Wordnik",
                    status=APIStatus.OK,
                    message="Wordnik API connected successfully.",
                    rate_limits=rate_info,
                )
            
            elif resp.status_code == 401:
                return APIStatusInfo(
                    name="Wordnik",
                    status=APIStatus.AUTH_ERROR,
                    message="Wordnik API key is invalid. Please check your WORDNIK_API_KEY.",
                    last_error="401 Unauthorized - Invalid API key",
                )
            
            elif resp.status_code == 403:
                return APIStatusInfo(
                    name="Wordnik",
                    status=APIStatus.AUTH_ERROR,
                    message="Wordnik API access denied. Your API key may be expired or revoked.",
                    last_error="403 Forbidden - Access denied",
                )
            
            elif resp.status_code == 429:
                rate_info = self._parse_wordnik_headers(resp.headers)
                self._rate_limits['wordnik'] = rate_info
                
                return APIStatusInfo(
                    name="Wordnik",
                    status=APIStatus.RATE_LIMITED,
                    message=f"Wordnik API rate limit exceeded. Wait {rate_info.format_wait_time()} or switch to Free Dictionary.",
                    rate_limits=rate_info,
                    last_error="429 Too Many Requests",
                )
            
            else:
                return APIStatusInfo(
                    name="Wordnik",
                    status=APIStatus.UNAVAILABLE,
                    message=f"Wordnik API returned unexpected status: {resp.status_code}",
                    last_error=f"HTTP {resp.status_code}",
                )
                
        except requests.exceptions.Timeout:
            return APIStatusInfo(
                name="Wordnik",
                status=APIStatus.UNAVAILABLE,
                message="Wordnik API timed out. The service may be temporarily unavailable.",
                last_error="Connection timeout",
            )
        except requests.exceptions.ConnectionError:
            return APIStatusInfo(
                name="Wordnik",
                status=APIStatus.UNAVAILABLE,
                message="Could not connect to Wordnik API. Check your internet connection.",
                last_error="Connection error",
            )
        except Exception as e:
            return APIStatusInfo(
                name="Wordnik",
                status=APIStatus.UNAVAILABLE,
                message=f"Error checking Wordnik API: {str(e)}",
                last_error=str(e),
            )
    
    def _parse_wordnik_headers(self, headers: Dict) -> RateLimitInfo:
        """Parse rate limit information from Wordnik response headers."""
        now = datetime.now()
        
        # Wordnik uses these headers (may vary):
        # X-RateLimit-Limit-minute
        # X-RateLimit-Remaining-minute
        # X-RateLimit-Limit-hour
        # X-RateLimit-Remaining-hour
        
        rate_info = RateLimitInfo(
            requests_per_minute=self.WORDNIK_LIMITS['requests_per_minute'],
            requests_per_hour=self.WORDNIK_LIMITS['requests_per_hour'],
            last_checked=now,
        )
        
        # Try to parse actual headers
        try:
            if 'X-RateLimit-Limit-minute' in headers:
                rate_info.requests_per_minute = int(headers['X-RateLimit-Limit-minute'])
            if 'X-RateLimit-Remaining-minute' in headers:
                rate_info.requests_remaining_minute = int(headers['X-RateLimit-Remaining-minute'])
            else:
                rate_info.requests_remaining_minute = rate_info.requests_per_minute
                
            if 'X-RateLimit-Limit-hour' in headers:
                rate_info.requests_per_hour = int(headers['X-RateLimit-Limit-hour'])
            if 'X-RateLimit-Remaining-hour' in headers:
                rate_info.requests_remaining_hour = int(headers['X-RateLimit-Remaining-hour'])
            else:
                rate_info.requests_remaining_hour = rate_info.requests_per_hour
        except (ValueError, KeyError):
            # Use defaults if headers aren't available
            rate_info.requests_remaining_minute = rate_info.requests_per_minute
            rate_info.requests_remaining_hour = rate_info.requests_per_hour
        
        # Calculate reset times
        rate_info.reset_time_minute = now + timedelta(minutes=1)
        rate_info.reset_time_hour = now + timedelta(hours=1)
        
        return rate_info
    
    def record_wordnik_request(self):
        """Record a Wordnik API request for rate tracking."""
        now = datetime.now()
        self._request_times['wordnik'].append(now)
        
        # Clean old entries
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        self._request_times['wordnik'] = [
            t for t in self._request_times['wordnik']
            if t > hour_ago
        ]
        
        # Update rate limit tracking
        if 'wordnik' in self._rate_limits:
            rate_info = self._rate_limits['wordnik']
            minute_requests = sum(1 for t in self._request_times['wordnik'] if t > minute_ago)
            hour_requests = len(self._request_times['wordnik'])
            
            rate_info.requests_remaining_minute = max(0, rate_info.requests_per_minute - minute_requests)
            rate_info.requests_remaining_hour = max(0, rate_info.requests_per_hour - hour_requests)
    
    def get_wordnik_rate_info(self) -> Optional[RateLimitInfo]:
        """Get current Wordnik rate limit information."""
        return self._rate_limits.get('wordnik')
    
    def should_wait_wordnik(self) -> Tuple[bool, int]:
        """
        Check if we should wait before making a Wordnik request.
        
        Returns:
            Tuple of (should_wait, seconds_to_wait)
        """
        rate_info = self._rate_limits.get('wordnik')
        if not rate_info:
            return False, 0
        
        if rate_info.is_rate_limited():
            return True, rate_info.wait_time_seconds()
        
        return False, 0
    
    def check_free_dictionary(self) -> APIStatusInfo:
        """Check Free Dictionary API availability."""
        try:
            url = f"{URLS['free_dictionary']}/test"
            resp = requests.get(url, timeout=10)
            
            # Free Dictionary returns 404 for unknown words, which is fine
            if resp.status_code in [200, 404]:
                return APIStatusInfo(
                    name="Free Dictionary",
                    status=APIStatus.OK,
                    message="Free Dictionary API is available.",
                )
            else:
                return APIStatusInfo(
                    name="Free Dictionary",
                    status=APIStatus.UNAVAILABLE,
                    message=f"Free Dictionary returned status {resp.status_code}",
                )
                
        except Exception as e:
            return APIStatusInfo(
                name="Free Dictionary",
                status=APIStatus.UNAVAILABLE,
                message=f"Could not connect to Free Dictionary: {str(e)}",
                last_error=str(e),
            )
    
    def check_datamuse(self) -> APIStatusInfo:
        """Check Datamuse API availability."""
        try:
            url = f"{URLS['datamuse']}?rel_syn=test&max=1"
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
                    message=f"Datamuse returned status {resp.status_code}",
                )
                
        except Exception as e:
            return APIStatusInfo(
                name="Datamuse",
                status=APIStatus.UNAVAILABLE,
                message=f"Could not connect to Datamuse: {str(e)}",
                last_error=str(e),
            )
    
    def check_all_apis(self) -> Dict[str, APIStatusInfo]:
        """Check status of all APIs."""
        return {
            'wordnik': self.check_wordnik_auth(),
            'free_dictionary': self.check_free_dictionary(),
            'datamuse': self.check_datamuse(),
        }
    
    def get_recommended_mode(self) -> Dict:
        """
        Get recommended generation mode based on API status.
        
        Returns:
            Dict with mode recommendation and explanation
        """
        wordnik_status = self.check_wordnik_auth()
        
        if wordnik_status.status == APIStatus.OK:
            return {
                'mode': 'wordnik',
                'quality': 'high',
                'message': 'Using Wordnik API for highest quality synonym/antonym data.',
                'rate_limits': wordnik_status.rate_limits.to_dict() if wordnik_status.rate_limits else None,
            }
        
        elif wordnik_status.status == APIStatus.RATE_LIMITED:
            wait_time = wordnik_status.rate_limits.wait_time_seconds() if wordnik_status.rate_limits else 0
            
            return {
                'mode': 'rate_limited',
                'quality': 'pending',
                'message': f'Wordnik rate limited. Options: wait {wordnik_status.rate_limits.format_wait_time()}, use overnight mode, or switch to Free Dictionary.',
                'wait_seconds': wait_time,
                'rate_limits': wordnik_status.rate_limits.to_dict() if wordnik_status.rate_limits else None,
                'options': [
                    {
                        'id': 'wait',
                        'label': f'Wait {wordnik_status.rate_limits.format_wait_time()}',
                        'description': 'Wait for rate limit to reset, then continue with Wordnik.',
                    },
                    {
                        'id': 'overnight',
                        'label': 'Overnight Mode',
                        'description': 'Process slowly overnight to stay within rate limits. Best quality.',
                    },
                    {
                        'id': 'free_dictionary',
                        'label': 'Use Free Dictionary',
                        'description': 'Switch to Free Dictionary for faster processing. Lower quality synonyms/antonyms.',
                    },
                ],
            }
        
        elif wordnik_status.status == APIStatus.NOT_CONFIGURED:
            return {
                'mode': 'free_dictionary',
                'quality': 'standard',
                'message': 'Wordnik not configured. Using Free Dictionary (standard quality).',
                'hint': 'Set WORDNIK_API_KEY for higher quality synonym/antonym data.',
            }
        
        else:
            return {
                'mode': 'free_dictionary',
                'quality': 'standard',
                'message': f'Wordnik unavailable ({wordnik_status.message}). Using Free Dictionary.',
                'error': wordnik_status.last_error,
            }


# Global tracker instance
_api_tracker: Optional[APIStatusTracker] = None


def get_api_tracker() -> APIStatusTracker:
    """Get or create the global API status tracker."""
    global _api_tracker
    if _api_tracker is None:
        _api_tracker = APIStatusTracker()
    return _api_tracker

"""In-memory storage backends with thread-safe LRU eviction and TTL expiration."""
import time
import threading
from typing import Any, Dict, Optional
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)

class InMemoryCacheBackend:
    """Thread-safe in-memory cache with LRU eviction and TTL expiration."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache = OrderedDict()
        self._access_times = {}
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache with LRU and TTL handling."""
        with self._lock:
            current_time = time.time()
            
            # Check if key exists
            if key not in self._cache:
                return None
            
            # Check TTL
            if key in self._access_times:
                if current_time - self._access_times[key] > self.ttl_seconds:
                    # Expired entry, remove it
                    del self._cache[key]
                    del self._access_times[key]
                    return None
            
            # Update LRU order
            self._cache.move_to_end(key)
            self._access_times[key] = current_time
            return self._cache[key]
    
    def set(self, key: str, value: Any) -> None:
        """Set a value in cache with LRU eviction."""
        with self._lock:
            current_time = time.time()
            self._cache[key] = value
            self._access_times[key] = current_time
            
            # Move to end for LRU
            self._cache.move_to_end(key)
            
            # Remove oldest if over size limit
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)
    
    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                if key in self._access_times:
                    del self._access_times[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear the entire cache."""
        with self._00004:
            self._cache.clear()
            self._access_times.clear()
    
    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)


class InMemorySessionBackend:
    """Thread-safe in-memory session storage with LRU eviction and TTL expiration."""
    
    def __init__(self, max_sessions: int = 50, session_ttl_seconds: int = 3600):
        self.max_sessions = max_sessions
        self.session_ttl_seconds = session_ttl_seconds
        self._sessions = OrderedDict()
        self._access_times = {}
        self._lock = threading.RLock()
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data with TTL handling."""
        with self._lock:
            current_time = time.time()
            
            # Check if session exists
            if session_id not in self._sessions:
                return None
            
            # Check TTL
            if session_id in self._access_times:
                if current_time - self._access_times[session_id] > self.session_ttl_seconds:
                    # Expired session, remove it
                    del self._sessions[session_id]
                    return None
            
            # Update LRU order
            self._sessions.move_to_end(session_id)
            self._access_times[session_id] = current_time
            return self._sessions[session_id].copy()
    
    def create_session(self, session_id: str, data: Dict) -> bool:
        """Create a new session with LRU eviction."""
        with self._lock:
            current_time = time.time()
            self._sessions[session_id] = data.copy()
            self._access_times[session_id] = current_time
            
            # Move to end for LRU
            self._sessions.move_to_end(session_id)
            
            # Remove oldest if over size limit
            if len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
            
            return True
    
    def update_session(self, session_id: str, data: Dict) -> bool:
        """Update an existing session."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].update(data)
                self._access_times[session_id] = time.time()
                self._sessions.move_to_end(session_id)
                return True
            return False
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                if session_id in self._access_times:
                    del self._access_times[session_id]
                return True
            return False
    
    def clear_sessions(self) -> None:
        """Clear all sessions."""
        with self._lock:
            self._sessions.clear()
            self._access_times.clear()
"""Redis storage backend with graceful fallback to in-memory storage when Redis is unavailable."""
import json
import logging
from typing import Any, Dict, Optional
import redis
from src.storage.memory import InMemoryCacheBackend, InMemorySessionBackend

logger = logging.getLogger(__name__)

class RedisCacheBackend:
    """Redis storage backend with graceful fallback to in-memory storage."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379", max_size: int = 1000, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
        self._redis_client = None
        self._redis_available = False
        self._in_memory_cache = InMemoryCacheBackend(max_size=max_size, ttl_seconds=ttl_seconds)
        self._in_memory_sessions = InMemorySessionBackend(max_sessions=50, session_ttl_seconds=ttl_seconds)
        
        # Try to connect to Redis
        try:
            self._redis_client = redis.Redis.from_url(redis_url)
            self._redis_client.ping()
            self._redis_available = True
        except Exception as e:
            logger.warning(f"Could not connect to Redis: {str(e)}. Falling back to in-memory storage.")
            self._redis_available = False

    def get(self, key: str) -> Optional[Any]:
        try:
            if self._redis_available and self._redis_client:
                value = self._redis_client.hget("cache", key)
                if value:
                    return json.loads(value)
        except Exception as e:
            logger.warning(f"Error accessing Redis, falling back to in-memory: {str(e)}")
        return self._in_memory_cache.get(key)

    def set(self, key: str, value: Any) -> None:
        try:
            if self._redis_available and self._redis_client:
                self._redis_client.hset("cache", key, json.dumps(value))
            else:
                self._in_memory_cache.set(key, value)
        except Exception as e:
            logger.warning(f"Error setting value in Redis: {str(e)}")
            self._in_memory_cache.set(key, value)

    def get_session(self, session_id: str) -> Optional[Dict]:
        try:
            if self._redis_available and self._redis_client:
                result = self._redis_client.hget("sessions", session_id)
                if result:
                    return json.loads(result)
            else:
                return self._in_memory_sessions.get_session(session_id)
        except Exception as e:
            logger.warning(f"Error accessing session: {str(e)}")
            return None

    def create_session(self, session_id: str, data: Dict) -> bool:
        try:
            if self._redis_available and self._redis_client:
                self._redis_client.hset("sessions", session_id, json.dumps(data))
                return True
            else:
                return self._in_memory_sessions.create_session(session_id, data)
        except Exception as e:
            logger.warning(f"Error creating session: {str(e)}")
            return False


class RedisSessionBackend:
    """Redis session backend with graceful fallback to in-memory storage."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379", max_sessions: int = 50, session_ttl_seconds: int = 3600):
        self.session_ttl_seconds = session_ttl_seconds
        self._redis_client = None
        self._redis_available = False
        self._in_memory_sessions = InMemorySessionBackend(max_sessions=max_sessions, session_ttl_seconds=session_ttl_seconds)
        
        # Try to connect to Redis
        try:
            self._redis_client = redis.Redis.from_url(redis_url)
            self._redis_client.ping()
            self._redis_available = True
        except Exception as e:
            logger.warning(f"Could not connect to Redis: {str(e)}. Falling back to in-memory storage.")
            self._redis_available = False

    def get_session(self, session_id: str) -> Optional[Dict]:
        try:
            if self._redis_available and self._redis_client:
                result = self._redis_client.hget("sessions", session_id)
                if result:
                    return json.loads(result)
            else:
                return self._in_memory_sessions.get_session(session_id)
        except Exception as e:
            logger.warning(f"Error accessing session: {str(e)}")
            return None

    def create_session(self, session_id: str, data: Dict) -> bool:
        try:
            if self._redis_available and self._redis_client:
                self._redis_client.hset("sessions", session_id, json.dumps(data))
                return True
            else:
                return self._in_memory_sessions.create_session(session_id, data)
        except Exception as e:
            logger.warning(f"Error creating session: {str(e)}")
            return False
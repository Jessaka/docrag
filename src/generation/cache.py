"""Response cache for generation results with route-specific TTLs."""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional

from config import settings
from src.generation.constants import RouteStrategy
from src.storage.memory import InMemoryCacheBackend
from src.storage.redis_impl import RedisCacheBackend


DEFAULT_ROUTE_TTLS: Dict[RouteStrategy, int] = {
    RouteStrategy.IDENTITY_DIRECT: 24 * 60 * 60,
    RouteStrategy.COMPARISON_DIRECT: 30 * 60,
    RouteStrategy.UNSUPPORTED_DIRECT: 6 * 60 * 60,
    RouteStrategy.CLARIFICATION_DIRECT: 10 * 60,
    RouteStrategy.DOCS_RAG: 30 * 60,
    RouteStrategy.SOFT_GUIDANCE_DIRECT: 15 * 60,
    RouteStrategy.FALLBACK_NO_ANSWER: 10 * 60,
    RouteStrategy.GENERIC_LLM: 5 * 60,
}


class ResponseCache:
    """Thin wrapper over the storage cache backends.

    The underlying backends use a single TTL. This wrapper stores per-entry
    expiration timestamps so different route strategies can have different TTLs.
    """

    def __init__(
        self,
        backend: Optional[Any] = None,
        route_ttls: Optional[Dict[RouteStrategy, int]] = None,
        namespace: str = "generation-response",
        max_size: int = 1000,
    ):
        self.namespace = namespace
        self.route_ttls = route_ttls or DEFAULT_ROUTE_TTLS.copy()
        max_ttl = max(self.route_ttls.values()) if self.route_ttls else settings.SESSION_TTL_SECONDS

        if backend is not None:
            self._backend = backend
        elif settings.USE_REDIS_CACHE and settings.REDIS_URL:
            self._backend = RedisCacheBackend(
                redis_url=settings.REDIS_URL,
                max_size=max_size,
                ttl_seconds=max_ttl,
            )
        else:
            self._backend = InMemoryCacheBackend(max_size=max_size, ttl_seconds=max_ttl)

    def build_key(self, route: RouteStrategy, query: str) -> str:
        """Build a stable cache key for a route + query pair."""
        digest = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
        return f"{self.namespace}:{route.value}:{digest}"

    def get(self, route: RouteStrategy, query: str) -> Optional[Dict[str, Any]]:
        """Return cached value when present and not expired."""
        key = self.build_key(route=route, query=query)
        payload = self._backend.get(key)
        if not payload:
            return None

        expires_at = payload.get("expires_at")
        if expires_at is not None and time.time() >= expires_at:
            if hasattr(self._backend, "delete"):
                self._backend.delete(key)
            return None

        return payload.get("value")

    def set(self, route: RouteStrategy, query: str, value: Dict[str, Any]) -> None:
        """Store a value using the TTL configured for the route."""
        ttl_seconds = self.route_ttls.get(route, settings.SESSION_TTL_SECONDS)
        key = self.build_key(route=route, query=query)
        self._backend.set(
            key,
            {
                "route": route.value,
                "expires_at": time.time() + ttl_seconds,
                "value": value,
            },
        )

    def delete(self, route: RouteStrategy, query: str) -> bool:
        """Delete a cached item if backend supports deletion."""
        if not hasattr(self._backend, "delete"):
            return False
        return bool(self._backend.delete(self.build_key(route=route, query=query)))

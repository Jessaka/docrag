"""Tavily web search integration for the fallback retrieval path."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT = 10.0


class TavilySearcher:
    """Thin async wrapper around the Tavily /search endpoint."""

    def __init__(self, api_key: str, max_results: int = 5) -> None:
        self._api_key = api_key
        self._max_results = max_results

    async def search(self, query: str, max_results: int | None = None) -> List[Dict[str, Any]]:
        """Search the web via Tavily and return a list of result dicts.

        Each result: {title, url, content, score}
        Returns [] on any error so callers can treat it as "no results".
        """
        n = max_results if max_results is not None else self._max_results
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": n,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(TAVILY_SEARCH_URL, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Tavily search HTTP error %s: %s", exc.response.status_code, exc)
            return []
        except Exception as exc:
            logger.warning("Tavily search failed: %s", exc)
            return []

        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title") or "",
                    "url": item.get("url") or "",
                    "content": item.get("content") or "",
                    "score": float(item.get("score") or 0.0),
                }
            )
        return results

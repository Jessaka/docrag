"""Reranker backend for improving retrieval precision.

Supports either a local sentence-transformers cross-encoder or NVIDIA hosted
reranking via NVIDIA's retrieval reranking API.
"""
import logging
import math
import json
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

from sentence_transformers import CrossEncoder

from config import settings
from src.retrieval.hybrid import SearchResult

logger = logging.getLogger(__name__)

# Default reranker models
DEFAULT_MODEL = settings.RERANKER_MODEL
DEFAULT_NVIDIA_MODEL = settings.RERANKER_NVIDIA_MODEL


class CrossEncoderReranker:
    """Reranks search results using either local or NVIDIA backend."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = settings.RERANKER_DEVICE,
        backend: str = settings.RERANKER_BACKEND,
        nvidia_model: str = DEFAULT_NVIDIA_MODEL,
    ):
        """Initialize the cross-encoder reranker.

        Args:
            model_name: HuggingFace model identifier for the cross-encoder.
            device: Device to load the model on (e.g. "cpu", "cuda").
        """
        self.model_name = model_name
        self.device = device
        self.backend = (backend or "nvidia").strip().lower()
        self.nvidia_model = nvidia_model
        self._nvidia_endpoint = (
            f"https://ai.api.nvidia.com/v1/retrieval/{self.nvidia_model}/reranking"
        )
        self._model: Optional[CrossEncoder] = None
        self._loaded = False

    def load(self) -> bool:
        """Prepare the configured reranker backend."""
        if self.backend not in {"nvidia", "local"}:
            logger.error("Unsupported reranker backend '%s'", self.backend)
            return False

        if self.backend == "nvidia":
            if not settings.NVIDIA_API_KEY:
                logger.error("NVIDIA reranker backend selected but NVIDIA_API_KEY is missing")
                return False

            self._loaded = True
            logger.info(
                "NVIDIA reranker enabled: %s (%s)",
                self.nvidia_model,
                self._nvidia_endpoint,
            )
            return True

        try:
            self._model = CrossEncoder(self.model_name, device=self.device)
            self._loaded = True
            logger.info(f"Cross-encoder loaded: {self.model_name} (device={self.device})")
            return True
        except Exception as e:
            logger.error(f"Failed to load cross-encoder model '{self.model_name}': {e}")
            return False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """Rerank search results using the cross-encoder.

        Creates (query, text) pairs and scores them with the cross-encoder.
        Results are sorted by cross-encoder score descending.

        Args:
            query: The user query.
            results: List of SearchResult objects to rerank.
            top_k: Optional limit on number of results to return after reranking.

        Returns:
            Reranked list of SearchResult objects with updated scores.
        """
        if not results:
            return []

        if not self._loaded:
            logger.warning("Reranker not loaded, returning original order")
            return results[:top_k] if top_k else results

        if self.backend == "nvidia":
            return self._rerank_with_nvidia(query=query, results=results, top_k=top_k)

        if self._model is None:
            logger.warning("Local cross-encoder not loaded, returning original order")
            return results[:top_k] if top_k else results

        try:
            # Prepare (query, text) pairs
            pairs: List[Tuple[str, str]] = [
                (query, result.text) for result in results
            ]

            # Get cross-encoder scores
            scores = self._model.predict(pairs)

            # Attach scores to results
            scored_results: List[Tuple[float, SearchResult]] = []
            for score, result in zip(scores, results):
                normalized_score = self._normalize_score(float(score))
                result.score = normalized_score
                scored_results.append((normalized_score, result))

            # Sort by score descending
            scored_results.sort(key=lambda x: x[0], reverse=True)

            reranked = [result for _, result in scored_results]

            if top_k:
                reranked = reranked[:top_k]

            logger.debug(
                f"Reranked {len(results)} results -> {len(reranked)} "
                f"(top score: {reranked[0].score:.4f})"
            )
            return reranked

        except Exception as e:
            logger.error(f"Cross-encoder reranking failed: {e}")
            return results[:top_k] if top_k else results

    def _rerank_with_nvidia(
        self,
        query: str,
        results: List[SearchResult],
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        documents = [result.text for result in results]
        payload = {
            "model": self.nvidia_model,
            "query": {"text": query},
            "passages": [{"text": document} for document in documents],
        }
        headers = {
            "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        }
        req = request.Request(
            self._nvidia_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=30) as response:
                response_data: Dict[str, Any] = json.loads(response.read().decode("utf-8"))

            rankings = response_data.get("rankings") or response_data.get("data") or []
            if not rankings:
                logger.warning("NVIDIA reranker returned no rankings; using original order")
                return results[:top_k] if top_k else results

            scored_results: List[Tuple[float, SearchResult]] = []
            seen_indices = set()
            for item in rankings:
                index = item.get("index")
                if not isinstance(index, int) or index < 0 or index >= len(results):
                    continue
                if index in seen_indices:
                    continue

                seen_indices.add(index)
                logit = float(item.get("logit", item.get("score", 0.0)))
                normalized_score = self._normalize_score(logit)
                result = results[index]
                result.score = normalized_score
                scored_results.append((normalized_score, result))

            if not scored_results:
                logger.warning("NVIDIA reranker returned unusable rankings; using original order")
                return results[:top_k] if top_k else results

            for index, result in enumerate(results):
                if index not in seen_indices:
                    scored_results.append((result.score, result))

            scored_results.sort(key=lambda item: item[0], reverse=True)

            reranked = [result for _, result in scored_results]
            if top_k:
                reranked = reranked[:top_k]

            logger.debug(
                "NVIDIA reranked %s results -> %s (top score: %.4f)",
                len(results),
                len(reranked),
                reranked[0].score if reranked else 0.0,
            )
            return reranked

        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            logger.warning("NVIDIA rerank HTTP error %s: %s", exc.code, details)
        except Exception as exc:
            logger.warning("NVIDIA rerank failed, using original order: %s", exc)

        return results[:top_k] if top_k else results

    @staticmethod
    def _normalize_score(score: float) -> float:
        return 1.0 / (1.0 + math.exp(-score))

    def rerank_with_threshold(
        self,
        query: str,
        results: List[SearchResult],
        min_score: float = 0.3,
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """Rerank and filter results below a minimum relevance threshold.

        Args:
            query: The user query.
            results: List of SearchResult objects to rerank.
            min_score: Minimum normalized score to include a result.
            top_k: Optional limit on number of results.

        Returns:
            Filtered and reranked list of SearchResult objects.
        """
        reranked = self.rerank(query, results, top_k=None)
        filtered = [r for r in reranked if r.score >= min_score]

        if top_k:
            filtered = filtered[:top_k]

        logger.debug(
            f"Threshold filter: {len(reranked)} -> {len(filtered)} "
            f"(min_score={min_score})"
        )
        return filtered

"""Cross-encoder reranker for improving retrieval precision.

Uses a sentence-transformers cross-encoder (configurable via RERANKER_MODEL,
default BAAI/bge-reranker-v2-m3 for multilingual support) to rescore
retrieved chunks against the query, producing more accurate relevance rankings.
"""
import logging
from typing import List, Optional, Tuple

from sentence_transformers import CrossEncoder

from config import settings
from src.retrieval.hybrid import SearchResult

logger = logging.getLogger(__name__)

# Default cross-encoder model
DEFAULT_MODEL = settings.RERANKER_MODEL


class CrossEncoderReranker:
    """Reranks search results using a cross-encoder model for better precision."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = settings.RERANKER_DEVICE):
        """Initialize the cross-encoder reranker.

        Args:
            model_name: HuggingFace model identifier for the cross-encoder.
            device: Device to load the model on (e.g. "cpu", "cuda").
        """
        self.model_name = model_name
        self.device = device
        self._model: Optional[CrossEncoder] = None
        self._loaded = False

    def load(self) -> bool:
        """Load the cross-encoder model into memory."""
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

        if not self._loaded or self._model is None:
            logger.warning("Cross-encoder not loaded, returning original order")
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
                # Cross-encoder scores can be negative; normalize to 0-1 range
                # using a simple sigmoid-like transformation
                normalized_score = 1.0 / (1.0 + float(2.71828 ** (-float(score))))
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
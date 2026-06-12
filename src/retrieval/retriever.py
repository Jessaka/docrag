"""DocsRetriever — main retrieval orchestrator.

Coordinates query classification, hybrid search (BM25 + Qdrant + RRF),
and cross-encoder reranking to produce the final set of relevant chunks.
"""
import logging
from typing import List, Optional, Dict, Any

from src.retrieval.hybrid import HybridRetriever, SearchResult
from src.retrieval.query_classifier import classify_query, QueryProfile
from src.retrieval.reranker import CrossEncoderReranker

logger = logging.getLogger(__name__)

# Default retrieval parameters
DEFAULT_TOP_K_PER_RETRIEVER = 20
DEFAULT_FINAL_TOP_K = 10
DEFAULT_MIN_RERANK_SCORE = 0.3


class DocsRetriever:
    """Orchestrates the full retrieval pipeline.

    Pipeline:
    1. Classify query → QueryProfile
    2. Generate query embedding (provided externally)
    3. Hybrid search: BM25 + Qdrant + RRF fusion
    4. Cross-encoder reranking
    5. Return top-k results
    """

    def __init__(
        self,
        hybrid_retriever: Optional[HybridRetriever] = None,
        reranker: Optional[CrossEncoderReranker] = None,
    ):
        """Initialize the DocsRetriever.

        Args:
            hybrid_retriever: Pre-configured HybridRetriever instance.
            reranker: Pre-configured CrossEncoderReranker instance.
        """
        self._hybrid = hybrid_retriever or HybridRetriever()
        self._reranker = reranker or CrossEncoderReranker()

    def initialize(self) -> bool:
        """Initialize all retrieval components.

        Returns:
            True if at least one retriever (BM25 or Qdrant) is available.
        """
        bm25_ok = self._hybrid.load_bm25()
        qdrant_ok = self._hybrid.connect_qdrant()
        reranker_ok = self._reranker.load()

        if not bm25_ok and not qdrant_ok:
            logger.error("Neither BM25 nor Qdrant is available. Cannot retrieve.")
            return False

        if not reranker_ok:
            logger.warning("Reranker not loaded. Results will not be reranked.")

        return True

    def retrieve(
        self,
        query: str,
        query_vector: List[float],
        top_k: int = DEFAULT_FINAL_TOP_K,
        provider_filter: Optional[str] = None,
        min_score: float = DEFAULT_MIN_RERANK_SCORE,
    ) -> Dict[str, Any]:
        """Run the full retrieval pipeline.

        Args:
            query: The user query string.
            query_vector: Pre-computed embedding vector for the query.
            top_k: Number of final results to return.
            provider_filter: Optional provider to restrict search to.
            min_score: Minimum reranker score threshold.

        Returns:
            Dictionary with:
                - results: List[SearchResult] — the final ranked chunks
                - query_profile: QueryProfile — classification result
                - stats: Dict — retrieval statistics
        """
        # Step 1: Classify the query
        query_profile = classify_query(query)

        # Step 2: Determine provider filter from classification.
        # Rules:
        # - Explicit provider_filter argument always wins (caller override).
        # - Comparison / multi-provider queries → no filter (cross-provider retrieval).
        # - Single provider detected with medium/high confidence → apply filter.
        # - Low confidence (no provider detected) → no filter.
        if provider_filter:
            # Explicit override from caller
            effective_provider = provider_filter
        elif query_profile.is_comparison or query_profile.is_multi_provider:
            # Comparison queries need cross-provider results
            effective_provider = None
        elif query_profile.provider_confidence in ("high", "medium"):
            # Single provider detected with sufficient confidence
            effective_provider = query_profile.primary_provider
        else:
            # Low confidence or no provider detected → cross-provider retrieval
            effective_provider = None

        # Step 3: Hybrid search
        search_results = self._hybrid.search(
            query=query,
            query_vector=query_vector,
            top_k=DEFAULT_TOP_K_PER_RETRIEVER,
            provider_filter=effective_provider,
        )

        stats = {
            "total_retrieved": len(search_results),
            "query_type": query_profile.query_type,
            "providers_detected": query_profile.providers,
            "tools_detected": query_profile.tools,
            "is_comparison": query_profile.is_comparison,
            "provider_filter_applied": effective_provider,
            "provider_confidence": query_profile.provider_confidence,
        }

        if not search_results:
            logger.info("No results from hybrid search")
            return {
                "results": [],
                "query_profile": query_profile,
                "stats": stats,
            }

        # Step 4: Rerank with cross-encoder
        if self._reranker.is_loaded:
            reranked = self._reranker.rerank_with_threshold(
                query=query,
                results=search_results,
                min_score=min_score,
                top_k=top_k,
            )
        else:
            reranked = search_results[:top_k]

        stats["final_count"] = len(reranked)
        stats["reranker_used"] = self._reranker.is_loaded

        logger.info(
            f"Retrieval complete: {stats['total_retrieved']} retrieved, "
            f"{stats['final_count']} after reranking (top_k={top_k})"
        )

        return {
            "results": reranked,
            "query_profile": query_profile,
            "stats": stats,
        }

    def retrieve_for_comparison(
        self,
        query: str,
        query_vector: List[float],
        providers: List[str],
        top_k_per_provider: int = 5,
    ) -> Dict[str, Any]:
        """Specialized retrieval for comparison queries.

        Searches separately for each provider and merges results.

        Args:
            query: The user query string.
            query_vector: Pre-computed embedding vector.
            providers: List of provider names to search.
            top_k_per_provider: Max results per provider.

        Returns:
            Dictionary with merged results from all providers.
        """
        all_results: List[SearchResult] = []
        stats: Dict[str, Any] = {
            "providers_searched": providers,
            "per_provider_counts": {},
        }

        for provider in providers:
            provider_results = self._hybrid.search(
                query=query,
                query_vector=query_vector,
                top_k=DEFAULT_TOP_K_PER_RETRIEVER,
                provider_filter=provider,
            )

            if self._reranker.is_loaded:
                provider_results = self._reranker.rerank(
                    query=query,
                    results=provider_results,
                    top_k=top_k_per_provider,
                )
            else:
                provider_results = provider_results[:top_k_per_provider]

            stats["per_provider_counts"][provider] = len(provider_results)
            all_results.extend(provider_results)

        # Deduplicate by URL
        seen_urls = set()
        deduped = []
        for r in all_results:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                deduped.append(r)

        query_profile = classify_query(query)
        stats["total_retrieved"] = len(all_results)
        stats["final_count"] = len(deduped)

        return {
            "results": deduped,
            "query_profile": query_profile,
            "stats": stats,
        }

    @property
    def is_ready(self) -> bool:
        """Check if the retriever is ready to serve queries."""
        return self._hybrid.is_ready

    @property
    def hybrid(self) -> HybridRetriever:
        return self._hybrid

    @property
    def reranker(self) -> CrossEncoderReranker:
        return self._reranker
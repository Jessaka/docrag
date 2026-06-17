"""Hybrid retrieval: BM25 keyword search + Qdrant vector search + RRF fusion.

Uses Reciprocal Rank Fusion (k=60) to combine results from both retrievers.
Limits to max 2 chunks per source (provider) to ensure diversity.

Provider-aware retrieval:
- When provider_filter is set, BM25 results are filtered to that provider only.
- After RRF fusion, results are post-filtered to the target provider.
- Cross-provider retrieval is preserved for comparison/multi-provider queries
  (pass provider_filter=None explicitly).
"""
import logging
import pickle
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, replace

import numpy as np
from rank_bm25 import BM25Okapi
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from config import settings
from src.retrieval.tokenizer import tokenize

logger = logging.getLogger(__name__)

RRF_K = 60
MAX_CHUNKS_PER_SOURCE = 2
# When provider filter is active, allow more chunks from the target provider
MAX_CHUNKS_PROVIDER_FILTERED = 10


@dataclass
class SearchResult:
    """Single search result from either BM25 or Qdrant."""
    text: str
    url: str
    title: str
    provider: str
    tool_name: str
    doc_type: str
    section: str
    chunk_index: int
    score: float
    source: str  # "bm25" or "qdrant"
    payload: Dict[str, Any]


class HybridRetriever:
    """Combines BM25 keyword search with Qdrant vector search using RRF fusion."""

    def __init__(
        self,
        bm25_index_path: Optional[str] = None,
        docs_store_path: Optional[str] = None,
        qdrant_host: Optional[str] = None,
        qdrant_port: Optional[int] = None,
        qdrant_collection: Optional[str] = None,
    ):
        self.bm25_index_path = bm25_index_path or settings.BM25_INDEX_PATH
        self.docs_store_path = docs_store_path or settings.DOCS_STORE_PATH
        self.qdrant_host = qdrant_host or settings.QDRANT_HOST
        self.qdrant_port = qdrant_port or settings.QDRANT_PORT
        self.qdrant_collection = qdrant_collection or settings.QDRANT_COLLECTION

        self._bm25: Optional[BM25Okapi] = None
        self._docs_store: List[Dict[str, Any]] = []
        self._qdrant_client: Optional[QdrantClient] = None
        self._bm25_loaded = False
        self._qdrant_connected = False

    def load_bm25(self) -> bool:
        """Load BM25 index and docs store from disk."""
        try:
            with open(self.bm25_index_path, "rb") as f:
                self._bm25 = pickle.load(f)
            with open(self.docs_store_path, "rb") as f:
                self._docs_store = pickle.load(f)
            self._bm25_loaded = True
            logger.info(f"BM25 index loaded: {len(self._docs_store)} documents")
            return True
        except FileNotFoundError:
            logger.warning(
                f"BM25 index not found at {self.bm25_index_path}. "
                "Run ingestion first."
            )
            return False
        except Exception as e:
            logger.error(f"Failed to load BM25 index: {e}")
            return False

    def connect_qdrant(self) -> bool:
        """Connect to Qdrant server."""
        try:
            self._qdrant_client = QdrantClient(
                host=self.qdrant_host, port=self.qdrant_port
            )
            # Verify connection by checking collection exists
            collections = self._qdrant_client.get_collections()
            collection_names = [c.name for c in collections.collections]
            if self.qdrant_collection not in collection_names:
                logger.warning(
                    f"Qdrant collection '{self.qdrant_collection}' not found. "
                    "Run ingestion first."
                )
                return False
            self._qdrant_connected = True
            logger.info(f"Qdrant connected: {self.qdrant_host}:{self.qdrant_port}")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to Qdrant: {e}")
            return False

    def search_bm25(
        self, query: str, top_k: int = 20, provider_filter: Optional[str] = None
    ) -> List[SearchResult]:
        """Perform BM25 keyword search.

        Args:
            query: The search query text.
            top_k: Number of results to return.
            provider_filter: If set, only return results from this provider.
                             Increases candidate pool to compensate for filtering.
        """
        if not self._bm25_loaded or self._bm25 is None:
            logger.warning("BM25 not loaded, returning empty results")
            return []

        tokenized_query = tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)

        # When filtering by provider, scan more candidates to find enough matches
        candidate_k = top_k * 10 if provider_filter else top_k * 3
        top_indices = np.argsort(scores)[::-1][:candidate_k]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            doc = self._docs_store[idx]
            # Apply provider filter: skip docs from other providers
            if provider_filter and doc.get("provider", "") != provider_filter:
                continue
            results.append(
                SearchResult(
                    text=doc.get("text", ""),
                    url=doc.get("url", ""),
                    title=doc.get("title", ""),
                    provider=doc.get("provider", ""),
                    tool_name=doc.get("tool_name", ""),
                    doc_type=doc.get("doc_type", ""),
                    section=doc.get("section", ""),
                    chunk_index=doc.get("chunk_index", 0),
                    score=float(scores[idx]),
                    source="bm25",
                    payload=doc,
                )
            )
            if len(results) >= top_k:
                break
        return results

    def search_qdrant(
        self, query_vector: List[float], top_k: int = 20, provider_filter: Optional[str] = None
    ) -> List[SearchResult]:
        """Perform Qdrant vector similarity search."""
        if not self._qdrant_connected or self._qdrant_client is None:
            logger.warning("Qdrant not connected, returning empty results")
            return []

        try:
            query_filter = None
            if provider_filter:
                query_filter = Filter(
                    must=[
                        FieldCondition(
                            key="provider", match=MatchValue(value=provider_filter)
                        )
                    ]
                )

            response = self._qdrant_client.search(
                collection_name=self.qdrant_collection,
                query_vector=query_vector,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
            )

            results = []
            for point in response:
                payload = point.payload or {}
                results.append(
                    SearchResult(
                        text=payload.get("text", ""),
                        url=payload.get("url", ""),
                        title=payload.get("title", ""),
                        provider=payload.get("provider", ""),
                        tool_name=payload.get("tool_name", ""),
                        doc_type=payload.get("doc_type", ""),
                        section=payload.get("section", ""),
                        chunk_index=payload.get("chunk_index", 0),
                        score=float(point.score),
                        source="vector",
                        payload=payload,
                    )
                )
            return results
        except Exception as e:
            logger.error(f"Qdrant search failed: {type(e).__name__}: {e}", exc_info=True)
            return []

    def rrf_fusion(
        self,
        bm25_results: List[SearchResult],
        qdrant_results: List[SearchResult],
        k: int = RRF_K,
    ) -> List[SearchResult]:
        """Combine BM25 and Qdrant results using Reciprocal Rank Fusion.

        RRF score = sum(1 / (k + rank_i)) for each retriever i.
        """
        # Build rank maps: key -> rank (1-indexed)
        bm25_ranks: Dict[str, int] = {}
        for rank, result in enumerate(bm25_results, start=1):
            key = self._result_key(result)
            if key not in bm25_ranks:
                bm25_ranks[key] = rank

        qdrant_ranks: Dict[str, int] = {}
        for rank, result in enumerate(qdrant_results, start=1):
            key = self._result_key(result)
            if key not in qdrant_ranks:
                qdrant_ranks[key] = rank

        # Collect all unique results
        all_results: Dict[str, SearchResult] = {}
        for r in bm25_results:
            key = self._result_key(r)
            if key not in all_results:
                all_results[key] = r
        for r in qdrant_results:
            key = self._result_key(r)
            if key not in all_results:
                all_results[key] = r

        # Compute RRF scores
        fused: List[tuple] = []
        for key, result in all_results.items():
            rrf_score = 0.0
            if key in bm25_ranks:
                rrf_score += 1.0 / (k + bm25_ranks[key])
            if key in qdrant_ranks:
                rrf_score += 1.0 / (k + qdrant_ranks[key])

            fused_result = replace(result)
            if key in bm25_ranks and key in qdrant_ranks:
                fused_result.source = "vector" if qdrant_ranks[key] <= bm25_ranks[key] else "bm25"

            fused.append((rrf_score, fused_result))

        # Sort by RRF score descending
        fused.sort(key=lambda x: x[0], reverse=True)

        return [result for _, result in fused]

    @staticmethod
    def _result_key(result: SearchResult) -> str:
        """Stable key for a unique retrieved chunk."""
        return f"{result.url}#{result.chunk_index}"

    def limit_per_source(
        self, results: List[SearchResult], provider_filter: Optional[str] = None
    ) -> List[SearchResult]:
        """Limit results to max chunks per provider.

        When provider_filter is active, allows more chunks from the target provider
        (MAX_CHUNKS_PROVIDER_FILTERED) and blocks all other providers entirely.
        Without a filter, applies the standard diversity cap (MAX_CHUNKS_PER_SOURCE).

        Args:
            results: Fused search results sorted by score.
            provider_filter: If set, only keep results from this provider.
        """
        if provider_filter:
            # Strict mode: only return chunks from the target provider
            limited = [r for r in results if r.provider == provider_filter]
            return limited[:MAX_CHUNKS_PROVIDER_FILTERED]

        # Diversity mode: cap per provider to ensure cross-provider balance
        provider_counts: Dict[str, int] = {}
        limited: List[SearchResult] = []
        for result in results:
            provider = result.provider or "unknown"
            count = provider_counts.get(provider, 0)
            if count < MAX_CHUNKS_PER_SOURCE:
                limited.append(result)
                provider_counts[provider] = count + 1
        return limited

    def search(
        self,
        query: str,
        query_vector: List[float],
        top_k: int = 20,
        provider_filter: Optional[str] = None,
    ) -> List[SearchResult]:
        """Run hybrid search: BM25 + Qdrant + RRF fusion + per-source limit.

        When provider_filter is set:
        - BM25 is restricted to that provider only.
        - Qdrant vector search is filtered to that provider only.
        - Post-fusion results are strictly limited to that provider.

        When provider_filter is None (comparison / multi-provider / low-confidence):
        - All providers are searched.
        - Diversity cap (MAX_CHUNKS_PER_SOURCE) is applied per provider.

        Args:
            query: The search query text (for BM25).
            query_vector: The embedding vector (for Qdrant).
            top_k: Number of candidates per retriever.
            provider_filter: Optional provider to restrict all retrieval to.

        Returns:
            Fused and limited list of SearchResult objects.
        """
        bm25_results = self.search_bm25(query, top_k=top_k, provider_filter=provider_filter)
        qdrant_results = self.search_qdrant(
            query_vector, top_k=top_k, provider_filter=provider_filter
        )

        if not bm25_results and not qdrant_results:
            logger.warning("Both BM25 and Qdrant returned no results")
            return []

        if not bm25_results:
            logger.info("Only Qdrant results available, skipping fusion")
            return self.limit_per_source(qdrant_results, provider_filter=provider_filter)

        if not qdrant_results:
            logger.info("Only BM25 results available, skipping fusion")
            return self.limit_per_source(bm25_results, provider_filter=provider_filter)

        fused = self.rrf_fusion(bm25_results, qdrant_results)
        limited = self.limit_per_source(fused, provider_filter=provider_filter)

        logger.info(
            f"Hybrid search: BM25={len(bm25_results)}, Qdrant={len(qdrant_results)}, "
            f"Fused={len(fused)}, Limited={len(limited)}, "
            f"provider_filter={provider_filter!r}"
        )
        return limited

    @property
    def is_ready(self) -> bool:
        """Check if both BM25 and Qdrant are available."""
        return self._bm25_loaded and self._qdrant_connected

    @property
    def bm25_loaded(self) -> bool:
        return self._bm25_loaded

    @property
    def qdrant_connected(self) -> bool:
        return self._qdrant_connected

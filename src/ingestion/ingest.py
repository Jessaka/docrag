"""Ingestion orchestration: scrape -> chunk -> embed -> upsert -> rebuild BM25."""

from __future__ import annotations

import logging
import os
import pickle
import uuid
from typing import Iterable, List, Optional, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from rank_bm25 import BM25Okapi

from config import settings
from src.ingestion.base_scraper import RawDocument
from src.ingestion.chunker import ChunkedDocument, chunk_documents
from src.ingestion.embedder import OpenAIEmbedder
from src.ingestion.scrapers.anthropic import AnthropicScraper
from src.ingestion.scrapers.codex import CodexScraper
from src.ingestion.scrapers.cursor import CursorScraper
from src.ingestion.scrapers.hermes import HermesScraper
from src.ingestion.scrapers.opencode import OpencodeScraper
from src.ingestion.scrapers.openclaw import OpenClawScraper

logger = logging.getLogger(__name__)

QDRANT_VECTOR_SIZE = 1536
UPSERT_BATCH_SIZE = 100


class IngestionOrchestrator:
    """Coordinates the full ingestion pipeline."""

    def __init__(
        self,
        scrapers: Optional[Sequence] = None,
        embedder: Optional[OpenAIEmbedder] = None,
        qdrant_client: Optional[QdrantClient] = None,
    ):
        self.scrapers = list(scrapers or self._default_scrapers())
        self.embedder = embedder or OpenAIEmbedder()
        self.qdrant_client = qdrant_client or QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )

    def run(self) -> dict:
        raw_documents = self.scrape_all()
        chunks = chunk_documents(raw_documents)
        embedded_points = self.embedder.embed_chunks(chunks)
        self.upsert_to_qdrant(embedded_points)
        self.rebuild_bm25(chunks)
        return {
            "raw_documents": len(raw_documents),
            "chunks": len(chunks),
            "embedded_points": len(embedded_points),
            "providers": sorted({document.provider for document in raw_documents}),
        }

    def scrape_all(self) -> List[RawDocument]:
        all_documents: List[RawDocument] = []
        for scraper in self.scrapers:
            try:
                docs = scraper.scrape()
                all_documents.extend(docs)
                logger.info("%s scraped %s documents", scraper.__class__.__name__, len(docs))
            except Exception as exc:
                logger.exception("Scraper %s failed: %s", scraper.__class__.__name__, exc)
        return all_documents

    def upsert_to_qdrant(self, embedded_points: Sequence[dict]) -> None:
        self._ensure_collection()
        points: List[PointStruct] = []
        for item in embedded_points:
            payload = item["payload"]
            point_id = self._build_point_id(
                provider=str(payload.get("provider", "")),
                url=str(payload["url"]),
                section=str(payload.get("section", "")),
                title=str(payload.get("title", "")),
                chunk_index=int(payload["chunk_index"]),
            )
            points.append(PointStruct(id=point_id, vector=item["vector"], payload=payload))

        for start in range(0, len(points), UPSERT_BATCH_SIZE):
            batch = points[start:start + UPSERT_BATCH_SIZE]
            if batch:
                self.qdrant_client.upsert(collection_name=settings.QDRANT_COLLECTION, points=batch)

    def rebuild_bm25(self, chunks: Sequence[ChunkedDocument]) -> None:
        os.makedirs(os.path.dirname(settings.BM25_INDEX_PATH), exist_ok=True)
        os.makedirs(os.path.dirname(settings.DOCS_STORE_PATH), exist_ok=True)

        docs_store = [chunk.to_payload() for chunk in chunks]
        if not docs_store:
            logger.warning("No chunks available; writing empty BM25 artifacts")
            with open(settings.BM25_INDEX_PATH, "wb") as file_handle:
                pickle.dump(None, file_handle)
            with open(settings.DOCS_STORE_PATH, "wb") as file_handle:
                pickle.dump([], file_handle)
            return
        tokenized_corpus = [chunk.text.lower().split() for chunk in chunks]
        bm25 = BM25Okapi(tokenized_corpus)

        with open(settings.BM25_INDEX_PATH, "wb") as file_handle:
            pickle.dump(bm25, file_handle)
        with open(settings.DOCS_STORE_PATH, "wb") as file_handle:
            pickle.dump(docs_store, file_handle)

    def _ensure_collection(self) -> None:
        collections = self.qdrant_client.get_collections()
        collection_names = {collection.name for collection in collections.collections}
        if settings.QDRANT_COLLECTION not in collection_names:
            self.qdrant_client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(size=QDRANT_VECTOR_SIZE, distance=Distance.COSINE),
            )

    def _default_scrapers(self) -> List:
        return [
            AnthropicScraper(),
            CursorScraper(),
            OpencodeScraper(),
            CodexScraper(),
            HermesScraper(),
            OpenClawScraper(),
        ]

    @staticmethod
    def _build_point_id(provider: str, url: str, section: str, title: str, chunk_index: int) -> str:
        unique_key = f"{provider}|{url}|{section}|{title}|{chunk_index}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, unique_key))


def run_ingestion(scrapers: Optional[Sequence] = None) -> dict:
    orchestrator = IngestionOrchestrator(scrapers=scrapers)
    return orchestrator.run()

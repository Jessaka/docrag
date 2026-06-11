"""Re-ingest only the Anthropic/Claude Code provider after a chunking fix.

Re-scrapes and re-chunks the Anthropic docs, then:
- Replaces only the "anthropic" points in the Qdrant collection.
- Replaces only the "anthropic" entries in the BM25 index / docs store,
  leaving all other providers untouched.
"""

from __future__ import annotations

import json
import logging
import pickle

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from rank_bm25 import BM25Okapi

from config import settings
from src.ingestion.chunker import chunk_documents
from src.ingestion.embedder import OpenAIEmbedder
from src.ingestion.ingest import IngestionOrchestrator
from src.ingestion.scrapers.anthropic import AnthropicScraper
from src.retrieval.tokenizer import tokenize


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    orchestrator = IngestionOrchestrator(scrapers=[AnthropicScraper()])

    raw_documents = orchestrator.scrape_all()
    chunks = chunk_documents(raw_documents)
    embedder = OpenAIEmbedder()
    embedded_points = embedder.embed_chunks(chunks)

    # --- Qdrant: drop old anthropic points, upsert new ones ---
    client: QdrantClient = orchestrator.qdrant_client
    orchestrator._ensure_collection()
    client.delete(
        collection_name=settings.QDRANT_COLLECTION,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(must=[qm.FieldCondition(key="provider", match=qm.MatchValue(value="anthropic"))])
        ),
    )
    orchestrator.upsert_to_qdrant(embedded_points)

    # --- BM25 / docs store: replace anthropic entries, keep everything else ---
    with open(settings.DOCS_STORE_PATH, "rb") as file_handle:
        existing_docs = pickle.load(file_handle)
    other_docs = [doc for doc in existing_docs if doc.get("provider") != "anthropic"]
    new_docs = [chunk.to_payload() for chunk in chunks]
    merged_docs = other_docs + new_docs

    tokenized_corpus = [tokenize(doc["text"]) for doc in merged_docs]
    bm25 = BM25Okapi(tokenized_corpus)

    with open(settings.BM25_INDEX_PATH, "wb") as file_handle:
        pickle.dump(bm25, file_handle)
    with open(settings.DOCS_STORE_PATH, "wb") as file_handle:
        pickle.dump(merged_docs, file_handle)

    print(json.dumps({
        "raw_documents": len(raw_documents),
        "anthropic_chunks": len(chunks),
        "other_provider_chunks": len(other_docs),
        "total_chunks": len(merged_docs),
    }, indent=2))


if __name__ == "__main__":
    main()

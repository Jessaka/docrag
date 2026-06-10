"""OpenAI embedding utilities for ingestion."""

from __future__ import annotations

import logging
import time
from typing import Iterable, List, Sequence

from openai import OpenAI

from config import settings
from src.ingestion.chunker import ChunkedDocument

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 100
MAX_EMBED_RETRIES = 3


class OpenAIEmbedder:
    """Batch embedder using OpenAI text-embedding-3-small."""

    def __init__(
        self,
        client: OpenAI | None = None,
        model: str = EMBEDDING_MODEL,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ):
        self.client = client or OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = model
        self.batch_size = batch_size

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start:start + self.batch_size])
            if not batch:
                continue
            response = None
            for attempt in range(1, MAX_EMBED_RETRIES + 1):
                try:
                    response = self.client.embeddings.create(model=self.model, input=batch)
                    break
                except Exception as exc:
                    if attempt == MAX_EMBED_RETRIES:
                        raise
                    logger.warning(
                        "Embedding batch failed on attempt %s/%s: %s",
                        attempt,
                        MAX_EMBED_RETRIES,
                        exc,
                    )
                    time.sleep(attempt)
            embeddings.extend([list(item.embedding) for item in response.data])
        return embeddings

    def embed_chunks(self, chunks: Sequence[ChunkedDocument]) -> List[dict]:
        texts = [chunk.text for chunk in chunks]
        vectors = self.embed_texts(texts)
        embedded: List[dict] = []
        for chunk, vector in zip(chunks, vectors):
            embedded.append(
                {
                    "vector": vector,
                    "payload": chunk.to_payload(),
                }
            )
        logger.info("Embedded %s chunks", len(embedded))
        return embedded

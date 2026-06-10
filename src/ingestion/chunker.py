"""Chunking utilities for documentation ingestion."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List

from src.ingestion.base_scraper import RawDocument

logger = logging.getLogger(__name__)

DOC_TYPE_TOKEN_LIMITS: Dict[str, int] = {
    "api_reference": 600,
    "guide": 800,
    "getting_started": 800,
    "model_card": 1000,
    "faq": 800,
    "config_reference": 800,
}


@dataclass
class ChunkedDocument(RawDocument):
    """Chunked document ready for embedding/upsert."""


def chunk_document(document: RawDocument) -> List[ChunkedDocument]:
    """Chunk a single raw document using doc-type specific strategy."""
    if document.doc_type == "changelog":
        return _chunk_changelog(document)
    if document.doc_type == "api_reference":
        return _chunk_api_reference(document)
    if document.doc_type in {"guide", "getting_started"}:
        return _chunk_by_h2_sections(document, token_limit=DOC_TYPE_TOKEN_LIMITS[document.doc_type])
    if document.doc_type == "model_card":
        return _chunk_single_or_split(document, token_limit=DOC_TYPE_TOKEN_LIMITS[document.doc_type])
    return _chunk_single_or_split(document, token_limit=DOC_TYPE_TOKEN_LIMITS.get(document.doc_type, 800))


def chunk_documents(documents: Iterable[RawDocument]) -> List[ChunkedDocument]:
    documents = list(documents)
    chunks: List[ChunkedDocument] = []
    for document in documents:
        chunks.extend(chunk_document(document))
    logger.info("Chunked %s documents into %s chunks", len(documents), len(chunks))
    return chunks


def _chunk_api_reference(document: RawDocument) -> List[ChunkedDocument]:
    blocks = _split_on_patterns(document.text, patterns=[r"\n(?=def\s)", r"\n(?=class\s)", r"\n(?=##\s)", r"\n(?=###\s)"])
    return _build_chunks_from_blocks(document, blocks, token_limit=DOC_TYPE_TOKEN_LIMITS["api_reference"])


def _chunk_by_h2_sections(document: RawDocument, token_limit: int) -> List[ChunkedDocument]:
    blocks = _split_on_patterns(document.text, patterns=[r"\n(?=##\s)", r"\n(?=[A-Z][A-Za-z0-9 /_-]{3,80}\n[-=]{3,})"])
    return _build_chunks_from_blocks(document, blocks, token_limit=token_limit)


def _chunk_single_or_split(document: RawDocument, token_limit: int) -> List[ChunkedDocument]:
    return _build_chunks_from_blocks(document, [document.text], token_limit=token_limit)


def _chunk_changelog(document: RawDocument) -> List[ChunkedDocument]:
    blocks = _split_on_patterns(
        document.text,
        patterns=[r"\n(?=#+\s*v?\d+\.\d+)", r"\n(?=Release\s+v?\d+\.\d+)", r"\n(?=Version\s+v?\d+\.\d+)"]
    )
    if not blocks:
        blocks = [document.text]
    chunks: List[ChunkedDocument] = []
    for index, block in enumerate(blocks):
        cleaned = block.strip()
        if not cleaned:
            continue
        version_match = re.search(r"\b(v?\d+\.\d+(?:\.\d+)?)\b", cleaned)
        section = version_match.group(1) if version_match else document.section
        payload = {**document.__dict__}
        payload.update(
            {
                "text": cleaned,
                "section": section,
                "chunk_index": index,
                "version": version_match.group(1) if version_match else document.version,
                "raw_html": "",
            }
        )
        chunks.append(
            ChunkedDocument(**payload)
        )
    return chunks


def _build_chunks_from_blocks(document: RawDocument, blocks: List[str], token_limit: int) -> List[ChunkedDocument]:
    chunks: List[ChunkedDocument] = []
    current_parts: List[str] = []
    current_tokens = 0
    chunk_index = 0

    for block in [part.strip() for part in blocks if part and part.strip()]:
        block_tokens = _estimate_tokens(block)
        if block_tokens > token_limit:
            sub_blocks = _split_long_text(block, token_limit)
        else:
            sub_blocks = [block]

        for sub_block in sub_blocks:
            sub_tokens = _estimate_tokens(sub_block)
            if current_parts and current_tokens + sub_tokens > token_limit:
                chunks.append(_make_chunk(document, "\n\n".join(current_parts), chunk_index))
                chunk_index += 1
                current_parts = []
                current_tokens = 0

            current_parts.append(sub_block)
            current_tokens += sub_tokens

    if current_parts:
        chunks.append(_make_chunk(document, "\n\n".join(current_parts), chunk_index))

    return chunks


def _make_chunk(document: RawDocument, text: str, chunk_index: int) -> ChunkedDocument:
    payload = {**document.__dict__}
    payload.update(
        {
            "text": text.strip(),
            "chunk_index": chunk_index,
            "raw_html": "",
        }
    )
    return ChunkedDocument(**payload)


def _split_on_patterns(text: str, patterns: List[str]) -> List[str]:
    if not text.strip():
        return []
    combined = "|".join(f"(?:{pattern})" for pattern in patterns)
    parts = re.split(combined, text)
    return [part for part in parts if part and part.strip()]


def _split_long_text(text: str, token_limit: int) -> List[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\n+", text) if part.strip()]
    if not paragraphs:
        return [text]

    parts: List[str] = []
    current: List[str] = []
    current_tokens = 0
    for paragraph in paragraphs:
        paragraph_tokens = _estimate_tokens(paragraph)
        if current and current_tokens + paragraph_tokens > token_limit:
            parts.append("\n\n".join(current))
            current = []
            current_tokens = 0

        if paragraph_tokens > token_limit:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            for sentence in sentences:
                if _estimate_tokens(sentence) > token_limit:
                    words = sentence.split()
                    step = max(50, int(token_limit / 1.3))
                    for index in range(0, len(words), step):
                        parts.append(" ".join(words[index:index + step]))
                else:
                    if current and current_tokens + _estimate_tokens(sentence) > token_limit:
                        parts.append("\n\n".join(current))
                        current = []
                        current_tokens = 0
                    current.append(sentence)
                    current_tokens += _estimate_tokens(sentence)
            continue

        current.append(paragraph)
        current_tokens += paragraph_tokens

    if current:
        parts.append("\n\n".join(current))
    return parts


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))

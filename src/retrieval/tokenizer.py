"""Shared tokenizer for BM25 indexing and querying.

Both indexing (ingest.py / reingest_anthropic.py) and querying (hybrid.py)
must use this exact function so tokens line up consistently (e.g. the query
token "hooks?" must match the indexed token "hooks").
"""

from __future__ import annotations

import re
from typing import List

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> List[str]:
    """Lowercase and split into word tokens, stripping punctuation."""
    return _TOKEN_RE.findall(text.lower())

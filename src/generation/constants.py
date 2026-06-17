"""Generation-layer constants."""

from enum import Enum


class RouteStrategy(str, Enum):
    """Allowed generation routes from ragdoc.md."""

    # Deterministic
    IDENTITY_DIRECT = "identity_direct"
    COMPARISON_DIRECT = "comparison_direct"
    UNSUPPORTED_DIRECT = "unsupported_direct"
    CLARIFICATION_DIRECT = "clarification_direct"

    # RAG routes
    DOCS_RAG = "docs_rag"
    SOFT_GUIDANCE_DIRECT = "soft_guidance_direct"
    FALLBACK_NO_ANSWER = "fallback_no_answer"

    # LLM
    GENERIC_LLM = "generic_llm"

    # Web search fallback
    WEB_SEARCH = "web_search"

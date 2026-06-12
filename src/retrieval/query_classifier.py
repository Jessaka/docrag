"""Query classifier for AI docs chatbot.

Classifies user queries into labels for query type, provider, and tool name.
Returns a QueryProfile used by the retriever to optimize search strategy.

Provider detection confidence:
- HIGH (2+ keyword hits for same provider): apply strict provider filter
- MEDIUM (1 keyword hit): apply provider filter
- LOW (0 hits, or ambiguous): no filter → cross-provider retrieval
"""
import logging
from dataclasses import dataclass, field
from typing import List, Set, Optional, Dict

logger = logging.getLogger(__name__)

# All valid query labels as defined in ragdoc.md
QUERY_LABELS: Set[str] = {
    # Query type
    "installation",
    "configuration",
    "api_reference",
    "getting_started",
    "model_comparison",
    "pricing",
    "code_example",
    "troubleshooting",
    "changelog",
    "faq",
    # Provider
    "provider:anthropic",
    "provider:cursor",
    "provider:opencode",
    "provider:openai",
    "provider:hermes",
    "provider:openclaw",
    # Tool name
    "tool:claude-code",
    "tool:cursor",
    "tool:opencode",
    "tool:codex",
    "tool:hermes",
    "tool:openclaw",
}

# Mapping of keywords/phrases to labels
_KEYWORD_TO_LABELS: dict = {
    # Query type keywords
    "install": "installation",
    "setup": "installation",
    "download": "installation",
    "configure": "configuration",
    "config": "configuration",
    "setting": "configuration",
    "api": "api_reference",
    "function": "api_reference",
    "method": "api_reference",
    "parameter": "api_reference",
    "endpoint": "api_reference",
    "get started": "getting_started",
    "quickstart": "getting_started",
    "first steps": "getting_started",
    "difference": "model_comparison",
    "compare": "model_comparison",
    "vs": "model_comparison",
    "versus": "model_comparison",
    "better": "model_comparison",
    "price": "pricing",
    "cost": "pricing",
    "free": "pricing",
    "tier": "pricing",
    "limit": "pricing",
    "example": "code_example",
    "code": "code_example",
    "snippet": "code_example",
    "error": "troubleshooting",
    "bug": "troubleshooting",
    "fix": "troubleshooting",
    "not working": "troubleshooting",
    "issue": "troubleshooting",
    "debug": "troubleshooting",
    "changelog": "changelog",
    "release": "changelog",
    "new": "changelog",
    "update": "changelog",
    "what is": "faq",
    "how to": "faq",
    "how do": "faq",
    "can i": "faq",
    "does": "faq",
    "support": "faq",
    # Provider keywords — Anthropic / Claude Code
    "anthropic": "provider:anthropic",
    "claude": "provider:anthropic",
    "claude code": "provider:anthropic",
    "claude-code": "provider:anthropic",
    "claude.ai": "provider:anthropic",
    "sonnet": "provider:anthropic",
    "haiku": "provider:anthropic",
    "opus": "provider:anthropic",
    # Provider keywords — Cursor
    "cursor": "provider:cursor",
    "cursor ide": "provider:cursor",
    "cursor editor": "provider:cursor",
    "cursor ai": "provider:cursor",
    "cursor tab": "provider:cursor",
    "cursor chat": "provider:cursor",
    "cursor composer": "provider:cursor",
    # Provider keywords — Opencode
    "opencode": "provider:opencode",
    "open code": "provider:opencode",
    # Provider keywords — OpenAI / Codex
    "openai": "provider:openai",
    "codex": "provider:openai",
    "codex cli": "provider:openai",
    "gpt": "provider:openai",
    "chatgpt": "provider:openai",
    "o1": "provider:openai",
    "o3": "provider:openai",
    # Provider keywords — Hermes
    "hermes": "provider:hermes",
    "nous": "provider:hermes",
    "nous hermes": "provider:hermes",
    "nous-hermes": "provider:hermes",
    # Provider keywords — OpenClaw
    "openclaw": "provider:openclaw",
    "open claw": "provider:openclaw",
    # Tool keywords (more specific — multi-word first for correct matching)
    "claude code": "tool:claude-code",
    "claude-code": "tool:claude-code",
    "cursor agent": "tool:cursor",
    "cursor ide": "tool:cursor",
    "opencode tool": "tool:opencode",
    "codex cli": "tool:codex",
    "hermes model": "tool:hermes",
    "openclaw tool": "tool:openclaw",
}


@dataclass
class QueryProfile:
    """Profile of a classified query with labels for routing and retrieval."""

    query: str
    query_type: str = "faq"  # Default to faq
    providers: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    all_labels: List[str] = field(default_factory=list)
    is_multi_provider: bool = False
    is_comparison: bool = False
    is_out_of_scope: bool = False
    # provider_hits: number of keyword matches per provider (used for confidence)
    provider_hits: Dict[str, int] = field(default_factory=dict)

    @property
    def primary_provider(self) -> Optional[str]:
        """Return the primary provider if exactly one is identified with sufficient confidence.

        Returns None when:
        - No provider detected
        - Multiple providers detected (comparison / multi-provider query)
        - Single provider detected but zero keyword hits (should not happen, but guard)
        """
        if len(self.providers) == 1:
            return self.providers[0]
        return None

    @property
    def provider_confidence(self) -> str:
        """Confidence level of provider detection.

        Returns:
            "high"   — 2+ keyword hits for the same provider
            "medium" — exactly 1 keyword hit
            "low"    — no provider detected or ambiguous (multi-provider)
        """
        if not self.providers or len(self.providers) > 1:
            return "low"
        provider = self.providers[0]
        hits = self.provider_hits.get(provider, 0)
        if hits >= 2:
            return "high"
        if hits == 1:
            return "medium"
        return "low"

    @property
    def primary_tool(self) -> Optional[str]:
        """Return the primary tool if exactly one is identified."""
        if len(self.tools) == 1:
            return self.tools[0]
        return None


def classify_query(query: str) -> QueryProfile:
    """Classify a user query into a QueryProfile with labels.

    Uses keyword matching to identify query type, providers, and tools.
    Tracks per-provider keyword hit counts to determine detection confidence.

    Confidence levels:
    - high (2+ hits): strong provider signal → apply strict provider filter
    - medium (1 hit): single keyword match → apply provider filter
    - low (0 hits or multi-provider): ambiguous → cross-provider retrieval

    Args:
        query: The raw user query string.

    Returns:
        QueryProfile with classified labels and provider_hits counts.
    """
    query_lower = query.lower().strip()
    labels: Set[str] = set()
    providers: Set[str] = set()
    tools: Set[str] = set()
    # Count keyword hits per provider for confidence scoring
    provider_hits: Dict[str, int] = {}

    # Sort keywords by length descending so multi-word phrases match before substrings
    sorted_keywords = sorted(_KEYWORD_TO_LABELS.keys(), key=len, reverse=True)

    for keyword in sorted_keywords:
        label = _KEYWORD_TO_LABELS[keyword]
        if keyword in query_lower:
            labels.add(label)
            if label.startswith("provider:"):
                provider_name = label.replace("provider:", "")
                providers.add(provider_name)
                provider_hits[provider_name] = provider_hits.get(provider_name, 0) + 1
            elif label.startswith("tool:"):
                tools.add(label.replace("tool:", ""))

    # Determine query type (first matched type label, default faq)
    type_labels = [
        "installation", "configuration", "api_reference", "getting_started",
        "model_comparison", "pricing", "code_example", "troubleshooting",
        "changelog", "faq",
    ]
    query_type = "faq"
    for t in type_labels:
        if t in labels:
            query_type = t
            break

    # Detect comparison queries
    is_comparison = "model_comparison" in labels or (
        len(providers) > 1 or len(tools) > 1
    )

    # Detect multi-provider queries
    is_multi_provider = len(providers) > 1

    # Detect out-of-scope queries (no provider/tool matched, no clear type)
    is_out_of_scope = (
        not providers
        and not tools
        and query_type == "faq"
        and not any(
            kw in query_lower
            for kw in ["ai", "code", "tool", "model", "llm", "agent", "chat"]
        )
    )

    profile = QueryProfile(
        query=query,
        query_type=query_type,
        providers=sorted(providers),
        tools=sorted(tools),
        all_labels=sorted(labels),
        is_multi_provider=is_multi_provider,
        is_comparison=is_comparison,
        is_out_of_scope=is_out_of_scope,
        provider_hits=provider_hits,
    )

    logger.debug(
        f"Classified query: type={query_type}, providers={providers}, "
        f"tools={tools}, comparison={is_comparison}, out_of_scope={is_out_of_scope}, "
        f"provider_hits={provider_hits}, confidence={profile.provider_confidence}"
    )
    return profile
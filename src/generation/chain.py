"""Generation chain orchestrating routing, retrieval, LLM calls, and caching."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from config import settings
from src.generation.cache import ResponseCache
from src.generation.constants import RouteStrategy
from src.generation.prompts import (
    QUERY_REWRITE_PROMPT,
    QUERY_REWRITE_PROMPT_WITH_CONTEXT,
    SYSTEM_PROMPT,
)
from src.retrieval.hybrid import SearchResult
from src.retrieval.query_classifier import QueryProfile, classify_query
from src.retrieval.retriever import DocsRetriever

logger = logging.getLogger(__name__)

CACHED_SYSTEM_PROMPT = [
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_CONTEXT_RESULTS = 5
MAX_OUTPUT_TOKENS = 1024

IDENTITY_QUERIES = {
    "who are you",
    "what are you",
    "kdo jsi",
    "co jsi",
}

# Czech-specific diacritic characters (both cases). Their presence is a
# cheap, dependency-free signal that a query is not English and needs
# translation before embedding against the English-only docs corpus.
_CZECH_DIACRITICS = set("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")


def _contains_czech_diacritics(text: str) -> bool:
    """Return True if text contains any Czech-specific diacritic character."""
    return any(char in _CZECH_DIACRITICS for char in text)


class DocsRAGChain:
    """High-level generation service for docs Q&A."""

    def __init__(
        self,
        retriever: Optional[DocsRetriever] = None,
        response_cache: Optional[ResponseCache] = None,
        anthropic_client: Optional[AsyncAnthropic] = None,
        embedding_client: Optional[AsyncOpenAI] = None,
        anthropic_model: Optional[str] = None,
        embedding_model: str = EMBEDDING_MODEL,
        max_context_results: int = MAX_CONTEXT_RESULTS,
    ):
        self._retriever = retriever or DocsRetriever()
        self._cache = response_cache or ResponseCache()
        self._anthropic = anthropic_client or AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._embedding_client = embedding_client or AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._anthropic_model = anthropic_model or settings.ANTHROPIC_MODEL
        self._embedding_model = embedding_model
        self._max_context_results = max_context_results
        self._retriever_initialized = False

    async def ask(
        self,
        query: str,
        previous_query: Optional[str] = None,
        last_strong_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate a non-streaming answer for a user query."""
        plan = await self._prepare(query, previous_query=previous_query, last_strong_profile=last_strong_profile)
        if plan["cached"]:
            return plan["cached_response"]

        route = plan["route"]
        direct_answer = self._direct_answer(route=route, query=query, query_profile=plan["query_profile"])
        if direct_answer is not None:
            response = self._build_response(
                answer=direct_answer,
                route=route,
                query=query,
                query_profile=plan["query_profile"],
                sources=plan["sources"],
                cached=False,
            )
            self._cache.set(route=route, query=query, value=response)
            return response

        answer = await self._generate_answer(query=query, route=route, context=plan["context"])
        response = self._build_response(
            answer=answer,
            route=route,
            query=query,
            query_profile=plan["query_profile"],
            sources=plan["sources"],
            cached=False,
        )
        self._cache.set(route=route, query=query, value=response)
        return response

    async def ask_stream(
        self,
        query: str,
        previous_query: Optional[str] = None,
        last_strong_profile: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream an answer as structured events."""
        plan = await self._prepare(query, previous_query=previous_query, last_strong_profile=last_strong_profile)
        if plan["cached"]:
            cached_response = plan["cached_response"]
            yield {
                "type": "meta",
                "route": cached_response["route"],
                "sources": cached_response["sources"],
                "cached": True,
            }
            yield {"type": "token", "text": cached_response["answer"]}
            yield {"type": "done", "response": cached_response}
            return

        route = plan["route"]
        yield {
            "type": "meta",
            "route": route.value,
            "sources": plan["sources"],
            "cached": False,
        }

        direct_answer = self._direct_answer(route=route, query=query, query_profile=plan["query_profile"])
        if direct_answer is not None:
            response = self._build_response(
                answer=direct_answer,
                route=route,
                query=query,
                query_profile=plan["query_profile"],
                sources=plan["sources"],
                cached=False,
            )
            self._cache.set(route=route, query=query, value=response)
            yield {"type": "token", "text": direct_answer}
            yield {"type": "done", "response": response}
            return

        collected_chunks: List[str] = []
        async with self._anthropic.messages.stream(
            model=self._anthropic_model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=CACHED_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_user_prompt(query, plan["context"])}],
        ) as stream:
            async for text in stream.text_stream:
                if not text:
                    continue
                collected_chunks.append(text)
                yield {"type": "token", "text": text}

        answer = "".join(collected_chunks).strip()
        response = self._build_response(
            answer=answer,
            route=route,
            query=query,
            query_profile=plan["query_profile"],
            sources=plan["sources"],
            cached=False,
        )
        self._cache.set(route=route, query=query, value=response)
        yield {"type": "done", "response": response}

    async def _prepare(
        self,
        query: str,
        previous_query: Optional[str] = None,
        last_strong_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        query_profile = classify_query(query)
        if self._is_weak_classification(query_profile) and last_strong_profile:
            # Inherit providers/tools/query_type from the last turn that
            # classified strongly, so follow-up questions ("Jak ho spustím
            # bez permisí?", "Jak to spustím ve WSL?") keep routing to the
            # right provider/tool across arbitrarily many weak turns.
            query_profile = QueryProfile(
                query=query,
                query_type=last_strong_profile.get("query_type", "faq"),
                providers=list(last_strong_profile.get("providers", [])),
                tools=list(last_strong_profile.get("tools", [])),
                all_labels=list(last_strong_profile.get("all_labels", [])),
                is_multi_provider=last_strong_profile.get("is_multi_provider", False),
                is_comparison=last_strong_profile.get("is_comparison", False),
                is_out_of_scope=False,
                provider_hits=dict(last_strong_profile.get("provider_hits", {})),
            )
        route = self._route_query(query=query, query_profile=query_profile)

        cached_response = self._cache.get(route=route, query=query)
        if cached_response is not None:
            cached_response = {**cached_response, "cached": True}
            return {
                "cached": True,
                "cached_response": cached_response,
                "query_profile": query_profile,
                "route": route,
                "results": [],
                "sources": cached_response.get("sources", []),
                "context": "",
            }

        results: List[SearchResult] = []
        route_after_retrieval = route
        if route in {RouteStrategy.DOCS_RAG, RouteStrategy.SOFT_GUIDANCE_DIRECT, RouteStrategy.FALLBACK_NO_ANSWER}:
            results = await self._retrieve_context(
                query=query, query_profile=query_profile, previous_query=previous_query
            )
            if results:
                route_after_retrieval = RouteStrategy.DOCS_RAG
            elif route == RouteStrategy.DOCS_RAG:
                route_after_retrieval = RouteStrategy.FALLBACK_NO_ANSWER

        sources = self._serialize_sources(results)
        context = self._format_context(results)
        return {
            "cached": False,
            "cached_response": None,
            "query_profile": query_profile,
            "route": route_after_retrieval,
            "results": results,
            "sources": sources,
            "context": context,
        }

    async def _retrieve_context(
        self, query: str, query_profile: QueryProfile, previous_query: Optional[str] = None
    ) -> List[SearchResult]:
        if not self._retriever_initialized:
            self._retriever.initialize()
            self._retriever_initialized = True

        # A follow-up turn's query text often relies on the previous turn for
        # its referent (e.g. "A na windows v power shell?"), so its own
        # query_profile (or one inherited from last_strong_profile) may not
        # signal that a rewrite is needed even though the raw text is not a
        # self-contained retrieval query. Always rewrite with context in that
        # case; eval queries have previous_query=None so this is a no-op there.
        if self._needs_rewrite(query_profile) or previous_query:
            retrieval_query = await self._rewrite_query(query, previous_query=previous_query)
        else:
            retrieval_query = query
        query_vector = await self._embed_query(retrieval_query)

        # Use retrieval_query (English after rewrite/translation) for BM25 and
        # reranking too, not just embedding - otherwise a Czech query_vector
        # still gets paired with raw Czech text for BM25/cross-encoder scoring
        # against the English-only corpus, which scores everything near zero.
        if query_profile.is_comparison and len(query_profile.providers) > 1:
            retrieval = self._retriever.retrieve_for_comparison(
                query=retrieval_query,
                query_vector=query_vector,
                providers=query_profile.providers,
            )
            # retrieve_for_comparison already caps results per provider, so
            # don't apply the single-provider max_context_results slice here —
            # that would drop every provider after the first.
            return retrieval.get("results", [])

        retrieval = self._retriever.retrieve(
            query=retrieval_query,
            query_vector=query_vector,
            provider_filter=query_profile.primary_provider,
        )
        return retrieval.get("results", [])[: self._max_context_results]

    def _is_weak_classification(self, query_profile: QueryProfile) -> bool:
        """Detect a classification with no usable provider/tool signal.

        Follow-up questions ("Jak ho spustím bez permisí?") often reference
        a tool named only in the previous turn, so classify_query has
        nothing to match on its own. This flags exactly that situation so
        _prepare can retry classification with the previous turn's text.
        """
        if query_profile.is_out_of_scope:
            return True
        return (
            query_profile.provider_confidence == "low"
            and not query_profile.providers
            and not query_profile.tools
        )

    def _needs_rewrite(self, query_profile: QueryProfile) -> bool:
        """Decide whether the extra rewrite round-trip is worth its latency.

        classify_query already extracted a provider/tool and a specific
        query_type (not the "faq" default) from keyword matches — that's
        enough signal for embedding/BM25 retrieval, so skip the rewrite.
        Genuinely vague queries (low confidence, no type label matched)
        still get rewritten to extract retrieval-relevant terms.

        Non-English (Czech) queries always need the rewrite regardless of
        confidence, since the docs corpus is English-only and the raw
        Czech text embeds poorly against it.
        """
        if _contains_czech_diacritics(query_profile.query):
            return True
        if query_profile.provider_confidence == "low":
            return True
        # Only rewrite faq queries with no detected provider/tool —
        # faq queries with a known provider are well-formed English and
        # rewriting them hurts BM25 recall (verified empirically).
        if query_profile.query_type == "faq" and not query_profile.providers and not query_profile.tools:
            return True
        return False

    async def _rewrite_query(self, query: str, previous_query: Optional[str] = None) -> str:
        """Rewrite the query for retrieval, falling back to the raw query.

        If previous_query is provided, the rewrite resolves references to
        the prior turn ("this", "ho", "to", ...) into a standalone question
        before translation, so follow-up queries retrieve correctly.
        """
        if previous_query:
            prompt = QUERY_REWRITE_PROMPT_WITH_CONTEXT.format(query=query, previous_query=previous_query)
        else:
            prompt = QUERY_REWRITE_PROMPT.format(query=query)

        try:
            response = await self._anthropic.messages.create(
                model=self._anthropic_model,
                max_tokens=128,
                system="You rewrite queries for document retrieval.",
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            text_blocks = [block.text for block in response.content if getattr(block, "type", None) == "text"]
            rewritten = "\n".join(text_blocks).strip()
            return rewritten or query
        except Exception as exc:
            logger.warning("Query rewrite failed, using raw query: %s", exc)
            return query

    async def _embed_query(self, query: str) -> List[float]:
        response = await self._embedding_client.embeddings.create(
            model=self._embedding_model,
            input=query,
        )
        return list(response.data[0].embedding)

    async def _generate_answer(self, query: str, route: RouteStrategy, context: str) -> str:
        response = await self._anthropic.messages.create(
            model=self._anthropic_model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=CACHED_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_user_prompt(query, context)}],
        )
        answer = "\n".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

        if not answer and route == RouteStrategy.FALLBACK_NO_ANSWER:
            return self._fallback_no_answer(query)
        return answer or self._fallback_no_answer(query)

    def _route_query(self, query: str, query_profile: QueryProfile) -> RouteStrategy:
        normalized = " ".join(query.lower().strip().split())
        if normalized in IDENTITY_QUERIES:
            return RouteStrategy.IDENTITY_DIRECT
        if query_profile.is_out_of_scope:
            return RouteStrategy.UNSUPPORTED_DIRECT
        if len(normalized.split()) <= 2:
            return RouteStrategy.CLARIFICATION_DIRECT
        if query_profile.is_comparison:
            # Cross-provider comparison ("Cursor vs Claude Code") -> docs_rag,
            # retrieve_for_comparison fans out per provider.
            if len(query_profile.providers) > 1 or len(query_profile.tools) > 1:
                return RouteStrategy.DOCS_RAG
            # Same-provider comparison ("Hermes 4 14B vs 70B") -> docs_rag,
            # retrieve normally with that provider's filter so the LLM gets
            # real grounded context to compare against.
            if len(query_profile.providers) == 1 or len(query_profile.tools) == 1:
                return RouteStrategy.DOCS_RAG
            # No specific provider/tool identified -> genuinely ambiguous,
            # ask the user what they want compared.
            return RouteStrategy.COMPARISON_DIRECT
        if query_profile.primary_provider or query_profile.primary_tool:
            return RouteStrategy.DOCS_RAG
        if any(token in normalized for token in ("api", "docs", "documentation", "install", "config", "error")):
            return RouteStrategy.DOCS_RAG
        return RouteStrategy.GENERIC_LLM

    def _direct_answer(
        self,
        route: RouteStrategy,
        query: str,
        query_profile: QueryProfile,
    ) -> Optional[str]:
        if route == RouteStrategy.IDENTITY_DIRECT:
            return (
                "I am a documentation assistant for AI coding tools. "
                "I can help with Claude Code, Cursor, Opencode, OpenAI Codex, Hermes, and OpenClaw."
            )
        if route == RouteStrategy.UNSUPPORTED_DIRECT:
            return (
                "This question appears to be outside the supported documentation scope. "
                "Please ask about Claude Code, Cursor, Opencode, OpenAI Codex, Hermes, or OpenClaw."
            )
        if route == RouteStrategy.CLARIFICATION_DIRECT:
            return (
                "Please clarify which tool or documentation area you mean so I can answer more precisely."
            )
        if route == RouteStrategy.COMPARISON_DIRECT:
            compared = ", ".join(query_profile.providers or query_profile.tools)
            if compared:
                return (
                    f"I can help compare {compared}. Please specify the aspect you want to compare, "
                    "such as installation, configuration, API usage, or pricing."
                )
            return "Please specify which two tools or providers you want to compare."
        if route == RouteStrategy.SOFT_GUIDANCE_DIRECT:
            return (
                "I could not find enough confident documentation context for a precise answer. "
                "Try naming the exact tool, feature, API, or error message."
            )
        if route == RouteStrategy.FALLBACK_NO_ANSWER:
            return self._fallback_no_answer(query)
        return None

    def _fallback_no_answer(self, query: str) -> str:
        return (
            "I could not find the answer in the available documentation context. "
            "Please rephrase the question or include the exact tool, feature, API, or error message."
        )

    def _format_context(self, results: List[SearchResult]) -> str:
        if not results:
            return ""

        blocks = []
        for index, result in enumerate(results, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"[Source {index}]",
                        f"Title: {result.title}",
                        f"URL: {result.url}",
                        f"Provider: {result.provider}",
                        f"Section: {result.section}",
                        "Context:",
                        result.text,
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _build_user_prompt(self, query: str, context: str) -> str:
        if context:
            return (
                "Answer the user's question using only the documentation context below.\n\n"
                f"Documentation context:\n{context}\n\n"
                f"User question: {query}"
            )
        return (
            "No documentation context was retrieved. If the answer is not in context, say so clearly.\n\n"
            f"User question: {query}"
        )

    def _serialize_sources(self, results: List[SearchResult]) -> List[Dict[str, Any]]:
        serialized: List[Dict[str, Any]] = []
        for result in results:
            serialized.append(
                {
                    "title": result.title,
                    "url": result.url,
                    "provider": result.provider,
                    "tool_name": result.tool_name,
                    "doc_type": result.doc_type,
                    "section": result.section,
                    "score": result.score,
                    "source": result.source,
                }
            )
        return serialized

    def _build_response(
        self,
        answer: str,
        route: RouteStrategy,
        query: str,
        query_profile: QueryProfile,
        sources: List[Dict[str, Any]],
        cached: bool,
        confidence: float = 1.0,
    ) -> Dict[str, Any]:
        return {
            "answer": answer,
            "route": route.value,
            "query": query,
            "cached": cached,
            "sources": sources,
            "confidence": confidence,
            "query_profile": {
                "query_type": query_profile.query_type,
                "providers": query_profile.providers,
                "tools": query_profile.tools,
                "all_labels": query_profile.all_labels,
                "is_multi_provider": query_profile.is_multi_provider,
                "is_comparison": query_profile.is_comparison,
                "is_out_of_scope": query_profile.is_out_of_scope,
                "provider_hits": query_profile.provider_hits,
            },
            "profile_is_weak": self._is_weak_classification(query_profile),
        }

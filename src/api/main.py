"""FastAPI application for the DocsRAG API layer."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any, AsyncIterator, Deque, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, root_validator

from config import settings
from src.generation.chain import DocsRAGChain
from src.storage.memory import InMemorySessionBackend
from src.storage.redis_impl import RedisSessionBackend

logger = logging.getLogger(__name__)

APP_TITLE = "DocsRAG API"
APP_VERSION = "0.1.0"
MAX_SESSION_POOL_SIZE = 50
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 30


class ChatRequest(BaseModel):
    """Request payload for chat endpoints. Accepts either 'query' or legacy 'question'."""

    query: Optional[str] = Field(None, min_length=1, max_length=2048)
    question: Optional[str] = Field(None, alias="question", min_length=1, max_length=2048)
    session_id: Optional[str] = Field(default=None, max_length=128)

    @root_validator(pre=True)
    def ensure_query(cls, values: dict) -> dict:
        """Ensure 'query' is set, using 'question' as fallback."""
        query = values.get('query') or values.get('question')
        if not query:
            raise ValueError('Either "query" or "question" must be provided and non-empty.')
        values['query'] = query
        return values


def create_session_pool() -> Any:
    """Create a session backend with TTL + LRU eviction."""
    max_sessions = min(settings.MAX_SESSIONS, MAX_SESSION_POOL_SIZE)
    if settings.USE_REDIS_CACHE and settings.REDIS_URL:
        return RedisSessionBackend(
            redis_url=settings.REDIS_URL,
            max_sessions=max_sessions,
            session_ttl_seconds=settings.SESSION_TTL_SECONDS,
        )
    return InMemorySessionBackend(
        max_sessions=max_sessions,
        session_ttl_seconds=settings.SESSION_TTL_SECONDS,
    )


app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    debug=settings.DEBUG_API_ERRORS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

session_pool = create_session_pool()
rag_chain = DocsRAGChain()
_rate_limit_lock = asyncio.Lock()
_request_windows: Dict[str, Deque[float]] = defaultdict(deque)


@app.middleware("http")
async def request_body_limit_middleware(request: Request, call_next):
    """Reject oversized request bodies early."""
    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "Request body too large."},
            )

        body = await request.body()
        if len(body) > settings.MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "Request body too large."},
            )

    return await call_next(request)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple per-IP sliding-window limiter."""
    if not settings.RATE_LIMIT_ENABLED:
        return await call_next(request)

    client_host = request.client.host if request.client else "unknown"
    now = time.time()

    async with _rate_limit_lock:
        window = _request_windows[client_host]
        while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
            window.popleft()

        if len(window) >= RATE_LIMIT_MAX_REQUESTS:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded."},
                headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
            )

        window.append(now)

    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Apply baseline security headers."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    return response


def _ensure_session(session_id: Optional[str], query: str) -> tuple[str, Optional[str]]:
    """Create or update a session in the pool.

    Returns the resolved session ID and the previous user query (if any),
    so the generation layer can fall back to conversational context for
    under-specified follow-up questions.
    """
    resolved_session_id = session_id or str(uuid.uuid4())
    session = session_pool.get_session(resolved_session_id)

    if session is None:
        session_pool.create_session(
            resolved_session_id,
            {
                "created_at": time.time(),
                "last_seen_at": time.time(),
                "message_count": 0,
            },
        )
        session = session_pool.get_session(resolved_session_id) or {}

    previous_query = session.get("last_user_query")

    session["last_seen_at"] = time.time()
    session["message_count"] = int(session.get("message_count", 0)) + 1
    session["last_user_query"] = query

    if hasattr(session_pool, "update_session"):
        session_pool.update_session(resolved_session_id, session)
    else:
        session_pool.create_session(resolved_session_id, session)

    return resolved_session_id, previous_query


async def _stream_chat_response(query: str, session_id: str, previous_query: Optional[str]) -> AsyncIterator[str]:
    """Serialize chain stream events into SSE format."""
    try:
        yield _sse_event(
            {
                "type": "session",
                "session_id": session_id,
            }
        )
        async for event in rag_chain.ask_stream(query, previous_query=previous_query):
            enriched_event = {**event, "session_id": session_id}
            yield _sse_event(enriched_event)
    except Exception as exc:
        logger.exception("Streaming chat request failed")
        yield _sse_event(
            {
                "type": "error",
                "session_id": session_id,
                "detail": str(exc) if settings.DEBUG_API_ERRORS else "Streaming request failed.",
            }
        )


def _sse_event(payload: Dict[str, Any]) -> str:
    """Format an SSE data event."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/chat")
async def chat(payload: ChatRequest) -> JSONResponse:
    """Return a single JSON response from the generation layer."""
    session_id, previous_query = _ensure_session(payload.session_id, payload.query)
    try:
        response = await rag_chain.ask(payload.query, previous_query=previous_query)
    except Exception as exc:
        logger.exception("Chat request failed")
        detail = str(exc) if settings.DEBUG_API_ERRORS else "Chat request failed."
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail) from exc

    return JSONResponse(
        content={
            "session_id": session_id,
            **response,
        }
    )


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """Stream a chat response over Server-Sent Events."""
    session_id, previous_query = _ensure_session(payload.session_id, payload.query)
    return StreamingResponse(
        _stream_chat_response(payload.query, session_id, previous_query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
async def health() -> JSONResponse:
    """Basic health endpoint."""
    session_count = None
    if hasattr(session_pool, "_sessions"):
        session_count = len(session_pool._sessions)

    return JSONResponse(
        content={
            "status": "ok",
            "service": APP_TITLE,
            "version": APP_VERSION,
            "rate_limit_enabled": settings.RATE_LIMIT_ENABLED,
            "max_request_body_bytes": settings.MAX_REQUEST_BODY_BYTES,
            "session_ttl_seconds": settings.SESSION_TTL_SECONDS,
            "max_sessions": min(settings.MAX_SESSIONS, MAX_SESSION_POOL_SIZE),
            "active_sessions": session_count,
        }
    )

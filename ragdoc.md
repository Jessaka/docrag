# AGENTS.md — AI Docs Chatbot

## Kontext projektu
Stavíme produkční RAG chatbot, který odpovídá na dotazy z dokumentací AI coding nástrojů.
Pokrývá: **Claude Code, Cursor, Opencode (sst/opencode), OpenAI Codex, Hermes (Nous Research), OpenClaw**.

Chatbot je určen pro vývojáře. Musí umět přesně odpovídat na otázky jako:
- "Jak nakonfiguruji custom agenta v Opencode?"
- "Jaký je rozdíl mezi Cursor Agent a Claude Code?"
- "Které modely Hermes podporují function calling?"

---

## Tech stack (neměň bez důvodu)

### Backend
- Python 3.12+
- FastAPI + Uvicorn
- Pydantic v2 pro request/response modely
- Hybridní retrieval: BM25 (rank_bm25) + Qdrant (qdrant-client)
- RRF fusion (Reciprocal Rank Fusion, k=60)
- Cross-encoder reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Generation: Anthropic API (claude-sonnet-4-20250514)
- Cache: in-memory s TTL, volitelně Redis
- Session management: per-session chain s TTL + LRU eviction

### Frontend
- SvelteKit
- Vanilla CSS (žádný Tailwind, žádný framework)
- SSE streaming přes fetch + ReadableStream

### Deployment
- Ubuntu (WSL pro vývoj, Hetzner VPS pro produkci)
- systemd služby pro backend
- nginx reverse proxy

---

## Adresářová struktura — PŘESNĚ TAKTO

```
ai-docs-chatbot/
├── AGENTS.md                    # tento soubor
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
├── config.py                    # všechny env proměnné a konstanty
│
├── src/
│   ├── api/
│   │   └── main.py              # FastAPI app, session pool, middleware, /chat, /chat/stream, /health
│   ├── generation/
│   │   ├── chain.py             # DocsRAGChain.ask() a ask_stream()
│   │   ├── prompts.py           # SYSTEM_PROMPT, QUERY_REWRITE_PROMPT
│   │   ├── cache.py             # ResponseCache s TTL
│   │   └── constants.py        # RouteStrategy enum
│   ├── retrieval/
│   │   ├── retriever.py         # DocsRetriever — hlavní retrieval třída
│   │   ├── hybrid.py            # BM25 + Qdrant + RRF fusion
│   │   ├── query_classifier.py  # classify_query() → QueryProfile
│   │   └── reranker.py          # cross-encoder reranker
│   ├── ingestion/
│   │   ├── base_scraper.py      # abstraktní BaseScraper
│   │   ├── scrapers/
│   │   │   ├── anthropic.py     # Claude Code docs (docs.anthropic.com/claude-code)
│   │   │   ├── cursor.py        # Cursor docs (cursor.com/docs)
│   │   │   ├── opencode.py      # Opencode docs (opencode.ai/docs + github sst/opencode)
│   │   │   ├── codex.py         # OpenAI Codex (platform.openai.com/docs)
│   │   │   ├── hermes.py        # Hermes (huggingface.co + github nous-research)
│   │   │   └── openclaw.py      # OpenClaw (docs.openclaw.ai)
│   │   ├── chunker.py           # inteligentní chunking podle doc_type
│   │   ├── embedder.py          # embedding přes OpenAI text-embedding-3-small
│   │   └── ingest.py            # orchestrace: scrape → chunk → embed → upsert do Qdrant + rebuild BM25
│   ├── storage/
│   │   ├── memory.py            # InMemoryCacheBackend + InMemorySessionBackend
│   │   └── redis_impl.py        # RedisCacheBackend (optional)
│   └── utils/
│       └── telemetry.py         # JSONL event logger (non-blocking)
│
├── frontend/
│   ├── package.json
│   ├── svelte.config.js
│   ├── vite.config.ts
│   └── src/
│       ├── lib/
│       │   └── api.ts           # fetch wrapper pro /chat a /chat/stream
│       └── routes/
│           └── +page.svelte     # hlavní chat UI
│
├── scripts/
│   ├── serve.py                 # lokální spuštění backendu
│   ├── ingest_all.py            # spustí ingestion pro všechny providery
│   └── smoke_test.py            # základní HTTP smoke testy
│
├── data/
│   ├── indexes/
│   │   └── bm25_index.pkl       # BM25 index (generovaný, v .gitignore)
│   └── docs_store.pkl           # raw docs pro BM25 (generovaný, v .gitignore)
│
└── evals/
    └── datasets/
        └── basic_eval_v1.json   # základní eval dataset
```

---

## Metadata schéma — každý dokument v Qdrant

Každý chunk musí mít tento payload. Bez výjimky.

```python
{
    # Povinná pole
    "text": str,                  # text chunku
    "url": str,                   # zdrojová URL nebo GitHub permalink
    "title": str,                 # název stránky/sekce
    "provider": str,              # "anthropic" | "cursor" | "opencode" | "openai" | "hermes" | "openclaw"
    "tool_name": str,             # "claude-code" | "cursor" | "opencode" | "codex" | "hermes" | "openclaw"
    "doc_type": str,              # "api_reference" | "guide" | "getting_started" | "changelog" | "faq" | "model_card" | "config_reference"
    "section": str,               # název sekce v dokumentu (např. "Installation", "Configuration")
    "chunk_index": int,           # pořadí chunku v dokumentu
    
    # Volitelná ale důležitá pole
    "version": str | None,        # verze nástroje pokud je známá (např. "0.3.1")
    "last_crawled": str,          # ISO datetime kdy byl crawlován
    "language": str,              # "en" (všechna dokumentace je anglicky)
    "is_deprecated": bool,        # True pokud je stránka označena jako deprecated
    "code_heavy": bool,           # True pokud chunk obsahuje >30% kódu
}
```

---

## Query classifier — labels pro novou doménu

`classify_query()` v `src/retrieval/query_classifier.py` musí vracet `QueryProfile` s těmito labels:

```python
QUERY_LABELS = {
    # Typ dotazu
    "installation",          # jak nainstalovat
    "configuration",         # jak nakonfigurovat
    "api_reference",         # API parametry, funkce, metody
    "getting_started",       # první kroky
    "model_comparison",      # porovnání modelů nebo nástrojů
    "pricing",               # ceny, limity, tier
    "code_example",          # žádám o příklad kódu
    "troubleshooting",       # debug, chyby, fix
    "changelog",             # co je nového, co se změnilo
    "faq",                   # obecné otázky
    
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
```

---

## Routing strategie (RouteStrategy enum)

Toto jsou JEDINÉ povolené hodnoty. Žádné bankovní routes (karty, hypotéky, SEPA atd.).

```python
class RouteStrategy(str, Enum):
    # Deterministické
    IDENTITY_DIRECT = "identity_direct"          # "kdo jsi?"
    COMPARISON_DIRECT = "comparison_direct"       # "jaký je rozdíl mezi X a Y?"
    UNSUPPORTED_DIRECT = "unsupported_direct"     # mimo scope
    CLARIFICATION_DIRECT = "clarification_direct" # nejednoznačný dotaz
    
    # RAG routes
    DOCS_RAG = "docs_rag"                        # standard RAG odpověď
    SOFT_GUIDANCE_DIRECT = "soft_guidance_direct" # když není dost docs
    FALLBACK_NO_ANSWER = "fallback_no_answer"     # žádné relevantní docs
    
    # LLM
    GENERIC_LLM = "generic_llm"                  # obecný dotaz bez retrieval
```

---

## Ingestion pipeline — jak funguje každý scraper

### Základní pravidla pro všechny scrapery
- Respektuj `robots.txt`
- Rate limit: max 2 requesty/sekundu na jeden domain
- User-Agent: `"ai-docs-chatbot/1.0 (educational project)"`
- Ukládej raw HTML do `/tmp/` cache pro re-run bez re-scraping
- Loguj co bylo scrapováno a co selhalo

### Chunking strategie podle doc_type
- `api_reference`: chunky podle funkce/metody (max 600 tokenů), zachovej signatury
- `guide` / `getting_started`: chunky podle H2 sekce (max 800 tokenů)
- `model_card`: jeden chunk na model (max 1000 tokenů)
- `changelog`: jeden chunk na verzi/release

### Embedding
- Model: `text-embedding-3-small` (OpenAI API)
- Batch size: 100 chunků najednou
- Upsert do Qdrant kolekce `ai_docs` s vector size 1536

---

## Generation — LLM instrukce

### Model
- Anthropic API, model: `claude-sonnet-4-20250514`

### System prompt (v `src/generation/prompts.py`)
```
You are a documentation assistant for AI coding tools.
You answer questions about: Claude Code, Cursor, Opencode, OpenAI Codex, Hermes, and OpenClaw.

Rules:
1. Answer ONLY from the provided documentation context.
2. If the answer is not in the context, say so clearly. Do NOT hallucinate.
3. Always cite the source URL.
4. For code examples, use the exact syntax from the docs.
5. If comparing tools, be factual and neutral.
6. Respond in the same language as the question.
```

---

## Co NESMÍŠ dělat

- ❌ Nevkládej žádný bankovní kód z RB projektu (žádné SEPA, karty, hypotéky, eKonto)
- ❌ Nepoužívej `langchain` — vše píšeme přímo
- ❌ Neinstaluj `transformers` pro embeddings — používáme OpenAI API
- ❌ Nedávej hardcoded API klíče do kódu — vždy přes `.env`
- ❌ Nepiš testy do `src/` — testy patří do `tests/`
- ❌ Nepoužívej synchronní HTTP v FastAPI endpointech — vždy `async`
- ❌ Nespouštěj ingestion jako součást `main.py` startu — ingestion je samostatný script

---

## Pořadí fází — DODRŽUJ TOTO POŘADÍ

### Fáze 1: Základní struktura projektu
1. Vytvoř všechny složky a prázdné `__init__.py`
2. Vytvoř `requirements.txt` s přesnými verzemi
3. Vytvoř `config.py` se všemi env proměnnými
4. Vytvoř `.env.example`
5. Vytvoř `.gitignore`

### Fáze 2: Storage vrstva
1. `src/storage/memory.py` — InMemoryCacheBackend + InMemorySessionBackend
2. `src/storage/redis_impl.py` — RedisCacheBackend (graceful fallback)

### Fáze 3: Retrieval vrstva
1. `src/retrieval/hybrid.py` — BM25 search + Qdrant vector search + RRF fusion
2. `src/retrieval/query_classifier.py` — classify_query() s labels výše
3. `src/retrieval/reranker.py` — cross-encoder reranker
4. `src/retrieval/retriever.py` — DocsRetriever orchestrace

### Fáze 4: Generation vrstva
1. `src/generation/constants.py` — RouteStrategy enum
2. `src/generation/prompts.py` — system prompt + query rewrite prompt
3. `src/generation/cache.py` — ResponseCache s TTL podle route
4. `src/generation/chain.py` — DocsRAGChain.ask() a ask_stream()

### Fáze 5: API vrstva
1. `src/api/main.py` — FastAPI app, session pool, /chat, /chat/stream, /health

### Fáze 6: Ingestion pipeline
1. `src/ingestion/base_scraper.py` — abstraktní BaseScraper
2. `src/ingestion/chunker.py` — chunking podle doc_type
3. `src/ingestion/embedder.py` — OpenAI embedding
4. Každý scraper v `src/ingestion/scrapers/`
5. `src/ingestion/ingest.py` — orchestrace

### Fáze 7: Frontend
1. SvelteKit projekt v `frontend/`
2. `frontend/src/lib/api.ts` — API klient
3. `frontend/src/routes/+page.svelte` — chat UI

### Fáze 8: Scripts a smoke testy
1. `scripts/serve.py`
2. `scripts/ingest_all.py`
3. `scripts/smoke_test.py`

---

## Environment proměnné (.env.example)

```bash
# LLM - Generation
ANTHROPIC_API_KEY=sk-ant-...

# Embeddings
OPENAI_API_KEY=sk-...

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=ai_docs

# BM25
BM25_INDEX_PATH=data/indexes/bm25_index.pkl
DOCS_STORE_PATH=data/docs_store.pkl

# API
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
MAX_REQUEST_BODY_BYTES=10240
RATE_LIMIT_ENABLED=false

# Cache
USE_REDIS_CACHE=false
REDIS_URL=redis://localhost:6379

# Session
SESSION_TTL_SECONDS=3600
MAX_SESSIONS=50

# Debug
DEBUG_API_ERRORS=false

# Telemetry
TELEMETRY_ENABLED=true
TELEMETRY_LOG_PATH=logs/telemetry.jsonl
TELEMETRY_QUERY_LOGGING=hashed
```

---

## Health check — `/health` musí vracet

```json
{
  "status": "ok",
  "qdrant": "ok" | "error",
  "bm25_index": "loaded" | "missing",
  "session_count": 0,
  "cache_stats": { "hits": 0, "misses": 0 }
}
```

---

## Jak spustit lokálně (pro README)

```bash
# 1. Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # doplň API klíče

# 2. Qdrant (Docker)
docker run -p 6333:6333 qdrant/qdrant

# 3. Ingestion
python scripts/ingest_all.py

# 4. Server
python scripts/serve.py

# 5. Frontend
cd frontend && npm install && npm run dev
```

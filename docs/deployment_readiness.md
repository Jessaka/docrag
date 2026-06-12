# Deployment Readiness Audit

Last updated: 2026-06-13

## Scope

This document audits the current DocsRAG repository for a **first production deployment**.

- Code changes: **none**
- Artifact created: **this document only**
- Deployment target considered: **single Hetzner VPS**

## Executive summary

**Current verdict:** **Not production-ready yet**, but **close enough for a first controlled deployment** after a small set of operational blockers is addressed.

Main reasons:

1. **No Dockerfile / compose setup** for the backend.
2. **No authentication** on `/chat` and `/chat/stream`.
3. **Rate limiting is disabled by default**.
4. **Bootstrap depends on a prior ingestion run** and on Qdrant being available.
5. **Telemetry is configured in settings/docs, but the referenced telemetry module is missing from the repo.**
6. **Health check is basic** and does not validate Qdrant/BM25 readiness.

That said, the app is lightweight enough to run on **one Hetzner VPS** if Qdrant is co-located and traffic is moderate.

---

## 1) Deployment checklist

### Required environment variables

From `config.py` and runtime usage:

| Variable | Required for first prod? | Notes |
|---|---:|---|
| `LLM_PROVIDER` | Yes | Default is `anthropic`. |
| `ANTHROPIC_API_KEY` | Yes | Required for generation with current default provider. |
| `ANTHROPIC_MODEL` | Yes | Current configured model: `claude-sonnet-4-6`. |
| `OPENAI_API_KEY` | Yes | Required for embeddings and ingestion. |
| `OPENAI_EMBED_MODEL` | Yes | Default `text-embedding-3-small`. |
| `QDRANT_HOST` | Yes | Vector store dependency. |
| `QDRANT_PORT` | Yes | Default `6333`. |
| `QDRANT_COLLECTION` | Yes | Default `ai_docs`. |
| `BM25_INDEX_PATH` | Yes | Default `data/indexes/bm25_index.pkl`. |
| `DOCS_STORE_PATH` | Yes | Default `data/docs_store.pkl`. |
| `CORS_ALLOWED_ORIGINS` | Yes | Must be set for production frontend origin(s). |
| `MAX_REQUEST_BODY_BYTES` | Yes | Default `10240`. |
| `RATE_LIMIT_ENABLED` | Yes | Should be `true` in production. |
| `SESSION_TTL_SECONDS` | Yes | Default `3600`. |
| `MAX_SESSIONS` | Yes | Default `50`. |
| `DEBUG_API_ERRORS` | Yes | Must be `false` in production. |

### Optional but important environment variables

| Variable | When needed | Notes |
|---|---|---|
| `NVIDIA_API_KEY` | If using NVIDIA reranker backend (default) or NVIDIA LLM | Current reranker default backend is `nvidia`. |
| `NVIDIA_BASE_URL` | If NVIDIA is used elsewhere | Present in config. |
| `NVIDIA_MODEL` | If NVIDIA LLM provider is enabled | Optional for current default path. |
| `GEMINI_API_KEY` | Only if Gemini provider is added/used | Optional. |
| `GEMINI_MODEL` | Same | Optional. |
| `RERANKER_BACKEND` | Recommended to set explicitly | Default is `nvidia`. |
| `RERANKER_MODEL` | If local reranker is used | Local cross-encoder model id. |
| `RERANKER_NVIDIA_MODEL` | If NVIDIA reranker is used | Default `nvidia/llama-nemotron-rerank-1b-v2`. |
| `RERANKER_DEVICE` | If local reranker is used | Default `cpu`. |
| `USE_REDIS_CACHE` | If enabling Redis-backed cache/sessions | Default `false`. |
| `USE_REDIS_SESSIONS` | Intended for Redis sessions | Present in config, not used by API bootstrap today. |
| `REDIS_URL` | Required only when Redis is enabled | Redis fallback logs warnings on failure. |
| `LLM_TEMPERATURE` | Optional tuning | Present in config. |
| `LLM_MAX_TOKENS` | Optional tuning | Present in config. |
| `LLM_TIMEOUT` | Optional tuning | Present in config. |
| `LLM_MAX_RETRIES` | Optional tuning | Present in config. |
| `TELEMETRY_ENABLED` | If telemetry implementation is restored/added | Config exists, module missing. |
| `TELEMETRY_LOG_PATH` | Same | Default `logs/telemetry.jsonl`. |
| `TELEMETRY_QUERY_LOGGING` | Same | Default `hashed`. |

### External services

| Service | Required? | Purpose |
|---|---:|---|
| Anthropic API | Yes | Main chat generation path. |
| OpenAI API | Yes | Embeddings during ingestion. |
| Qdrant | Yes | Vector retrieval store. |
| NVIDIA API | Likely yes with current defaults | Default reranker backend is `nvidia`; without key it may degrade or fail to rerank depending on code path. |
| Redis | No | Optional cache/session persistence. |

### Anthropic dependency

- Python dependency: `anthropic>=0.50.0`
- Runtime use: `AsyncAnthropic` in `src/generation/chain.py`
- Current model: `claude-sonnet-4-6`
- Outbound internet access required
- Production concern: no auth on public API means Anthropic usage can be abused and generate cost

### NVIDIA dependency

- Python code supports NVIDIA-hosted reranking in `src/retrieval/reranker.py`
- Current default reranker backend in `config.py` is `nvidia`
- If `NVIDIA_API_KEY` is not set and backend remains `nvidia`, retrieval quality may degrade because reranking cannot be loaded
- If avoiding NVIDIA in first deploy, config should later be explicitly switched to local reranker, but that is outside this audit

### Qdrant dependency

- Required for vector retrieval and ingestion upserts
- Used by:
  - `src/ingestion/ingest.py`
  - `src/retrieval/hybrid.py`
- Collection must exist or ingestion must create it first
- Default port: `6333`
- Persistence required for production data retention

### Storage requirements

Persistent data/storage areas:

| Path / store | Purpose | Persistence needed? |
|---|---|---:|
| `data/indexes/bm25_index.pkl` | BM25 index | Yes |
| `data/docs_store.pkl` | Serialized docs for BM25 | Yes |
| Qdrant collection `ai_docs` | Vector store | Yes |
| `logs/` | App/telemetry logs if enabled | Recommended |
| `/tmp/...html-cache` | Scraper cache | No for runtime API, useful for ingestion reruns |

### Startup sequence

Recommended first-production startup order:

1. Provision `.env` / secret injection.
2. Start **Qdrant**.
3. Optionally start **Redis**.
4. Run **ingestion/bootstrap** once:
   - `python scripts/ingest_all.py`
5. Verify BM25 files exist and Qdrant collection exists.
6. Start backend:
   - `python scripts/serve.py --host 0.0.0.0 --port 8000`
7. Put backend behind reverse proxy / TLS terminator.
8. Check `/health`.
9. Run a smoke query on `/chat` and `/chat/stream`.

### Health checks

Current endpoint:

- `GET /health`

Current fields:

- `status`
- `service`
- `version`
- `rate_limit_enabled`
- `max_request_body_bytes`
- `session_ttl_seconds`
- `max_sessions`
- `active_sessions`

Current health gap:

- Does **not** verify Qdrant connectivity
- Does **not** verify BM25 index loadability
- Does **not** verify Anthropic/OpenAI reachability
- Does **not** expose cache or reranker readiness

### Logging

- App logging is configured via `logging.basicConfig(... level=INFO ...)` in `scripts/serve.py`
- Logs go to stdout/stderr
- `logger.exception(...)` is used in API error paths
- Telemetry is referenced in config/docs but the actual `src/utils/telemetry.py` file is **missing** in the current repository snapshot

### Backup considerations

Minimum backup scope:

1. `data/indexes/bm25_index.pkl`
2. `data/docs_store.pkl`
3. Qdrant persistent storage / snapshots
4. `.env` should **not** be backed up into general-purpose logs/artifacts without encryption

Recommended backup policy:

- Daily snapshot of Qdrant data
- Daily backup of `data/` artifacts
- At least 7 daily + 4 weekly retention
- Store backups encrypted at rest
- Test restore procedure before production launch

### Security concerns

Highest-priority concerns before launch:

1. **No endpoint authentication**
2. **Rate limiting disabled by default**
3. **Debug errors can expose internals if enabled**
4. **Potential prompt-injection / cost abuse on public chat endpoints**
5. **Redis warnings may reveal connection details if secrets are embedded in URLs**
6. **NVIDIA HTTP error logging may expose too much response detail**
7. **CORS must be restricted to real frontend origins**

### Secret management

Required practices:

- Do **not** commit `.env`
- Inject secrets via:
  - systemd environment file with strict permissions, or
  - Docker secrets / mounted env file, or
  - external secret manager
- Restrict permissions on secret files to owner-only
- Never place secrets inside logged URLs if avoidable
- Rotate Anthropic/OpenAI/NVIDIA keys periodically

---

## 2) Docker readiness / VPS suitability / sizing

### Is the project Docker-ready?

**Verdict: No, not yet.**

Why:

- No `Dockerfile`
- No `docker-compose.yml`
- No container startup/wait-for-dependencies script
- No documented production container flow for backend + Qdrant + optional Redis

What is encouraging:

- Backend is a simple Python/FastAPI service
- Config is env-based
- External services are cleanly separated
- It should be straightforward to containerize later

### Can it run on a single Hetzner VPS?

**Verdict: Yes**, for first production, if:

- Qdrant runs on the same machine or nearby
- traffic is modest
- ingestion is not run constantly under user load
- reverse proxy/TLS is configured

### Recommended Hetzner sizing

#### Minimum viable

- **CPU:** 2 vCPU
- **RAM:** 4 GB
- **Disk:** 40 GB SSD

Suitable for:

- one backend instance
- co-located Qdrant
- modest doc corpus
- low to moderate traffic

#### Recommended comfortable first production

- **CPU:** 4 vCPU
- **RAM:** 8 GB
- **Disk:** 80 GB SSD

Recommended because:

- leaves room for Qdrant memory use
- leaves room for local reranker fallback if needed later
- leaves headroom for logs, snapshots, and ingestion artifacts

#### If local reranker replaces NVIDIA later

Prefer:

- **CPU:** 4+ vCPU
- **RAM:** 8-16 GB

because `sentence-transformers` cross-encoder on CPU can increase memory/startup costs.

---

## 3) Deployment blockers

### Blockers to resolve before first public deployment

1. **No auth on `/chat` and `/chat/stream`**
   - Public exposure risks cost abuse and endpoint misuse.

2. **`RATE_LIMIT_ENABLED` defaults to false**
   - This should be explicitly enabled in production.

3. **No Docker packaging**
   - If deployment strategy expects containers, this is an immediate blocker.

4. **Health endpoint is too shallow for production operations**
   - It does not validate Qdrant or BM25 readiness.

5. **Ingestion/bootstrap is a manual prerequisite**
   - Service may come up “healthy” while retrieval data is absent.

6. **Telemetry/config mismatch**
   - `config.py` references telemetry settings and `ragdoc.md` references `src/utils/telemetry.py`, but that file is missing.
   - This is at minimum a documentation/config drift issue and should be clarified before launch.

7. **Reranker dependency needs an explicit production decision**
   - Current defaults point to NVIDIA reranking.
   - Production runbook must explicitly state whether NVIDIA is required or whether degraded/no-rerank mode is acceptable.

### Optional improvements

1. Add Dockerfile and compose file.
2. Add startup readiness checks for Qdrant and BM25.
3. Add structured logging / log rotation.
4. Add backup automation and restore runbook.
5. Add external monitoring/alerting.
6. Add API auth and quotas.
7. Add stricter validation for `session_id` and deployment env sanity checks.
8. Add secret redaction filter for logs.

---

## 4) Recommended production runbook

### Pre-deploy

- [ ] Prepare secrets securely
- [ ] Start Qdrant with persistent volume
- [ ] Decide whether Redis is enabled
- [ ] Decide whether NVIDIA reranker is enabled
- [ ] Run ingestion successfully
- [ ] Confirm BM25 files exist
- [ ] Confirm Qdrant collection exists and has points
- [ ] Set production CORS origins
- [ ] Set `RATE_LIMIT_ENABLED=true`
- [ ] Set `DEBUG_API_ERRORS=false`

### Deploy

- [ ] Start backend service
- [ ] Confirm `GET /health` returns 200
- [ ] Run one `/chat` smoke test
- [ ] Run one `/chat/stream` smoke test
- [ ] Confirm reverse proxy / TLS works

### Post-deploy

- [ ] Verify logs are being captured
- [ ] Verify backups are scheduled
- [ ] Verify disk growth expectations
- [ ] Verify Qdrant persistence / restart behavior
- [ ] Review Anthropic/OpenAI/NVIDIA usage costs after first traffic

---

## 5) Go / no-go

### No-go for public internet launch until:

- auth strategy is defined
- rate limiting is enabled
- bootstrap/ingestion dependency is operationally documented and verified
- health/readiness expectations are improved or externally compensated

### Go for controlled/private first deployment if:

- traffic is limited
- access is restricted
- Qdrant persistence is configured
- secrets are managed safely
- ingestion has already been run
- operational team accepts manual bootstrap and shallow health checks

---

## Source basis for this audit

Primary files inspected:

- `config.py`
- `requirements.txt`
- `src/api/main.py`
- `src/generation/chain.py`
- `src/retrieval/hybrid.py`
- `src/retrieval/reranker.py`
- `src/ingestion/ingest.py`
- `src/storage/redis_impl.py`
- `scripts/serve.py`
- `scripts/ingest_all.py`
- `ragdoc.md`

## Final recommendation

For a **first production deployment**, prefer:

- **1× Hetzner VPS, 4 vCPU / 8 GB RAM / 80 GB SSD**
- backend + Qdrant on the same host
- optional Redis only if session/cache persistence is truly needed
- restricted access until auth/rate limiting are in place

This project is **deployable soon**, but **not yet fully production-ready** without a short round of DevOps and security hardening.

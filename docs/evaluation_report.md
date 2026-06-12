# Evaluation Report

Source files:
- `tests/evaluation_queries.json`
- `tests/evaluation_results.json`

Generated evaluation summary from results:
- Total queries: **60**
- Provider hit rate: **91.67%**
- Route match rate: **91.67%**
- Source hit rate: **73.33%**
- Has-answer rate: **95.00%**
- Average latency: **12.59 s**

## Executive summary

The evaluation mostly succeeds on provider detection and route selection, but it underperforms on **source grounding**.

The main failure theme is **benchmark-targeted documentation not being retrieved from the exact expected URLs**, especially for:
- Claude Code org setup
- Codex configuration / permissions
- Hermes model-card targets
- OpenClaw install / setup / config / troubleshooting / multi-agent docs

The second major issue is **routing/classifier misses for Hermes**, where several queries never reached `docs_rag` and instead fell back to `fallback_no_answer` or `comparison_direct`.

There is **no strong evidence of a generation-layer bug**. Most bad outcomes are upstream of generation.

## Root-cause grouping

### 1. Missing documentation coverage
Definition: the system answered from same-provider docs, but none of the returned sources matched the expected target URLs.

Affected queries:
- `anthropic_03_configuration_org`
- `openai_02_configuration_basic`
- `openai_06_permissions`
- `hermes_02_configuration_system_prompt`
- `hermes_04_agents`
- `hermes_08_json_mode`
- `openclaw_01_install`
- `openclaw_02_setup`
- `openclaw_03_configuration`
- `openclaw_07_multi_agent`
- `openclaw_09_troubleshooting`

### 2. Routing/classifier miss
Definition: the system failed to keep the query on the expected `docs_rag` route and/or failed to retain the expected provider.

Affected queries:
- `hermes_05_mcp_tools`
- `hermes_06_permissions_safety`
- `hermes_07_troubleshooting_quantization`
- `hermes_09_reasoning`
- `hermes_10_comparison_variants`

### 3. Retrieval miss
Definition: the relevant provider likely exists, but the specific expected doc did not surface even though adjacent docs did.

Affected queries:
- `anthropic_03_configuration_org`
- `openai_02_configuration_basic`
- `openai_06_permissions`
- `openclaw_01_install`
- `openclaw_02_setup`
- `openclaw_03_configuration`
- `openclaw_07_multi_agent`
- `openclaw_09_troubleshooting`

Note: these overlap with missing coverage. In practice, some are likely true indexing gaps, while others are ranking/coverage hybrids.

### 4. Benchmark expectation issue
Definition: benchmark expects too-specific URLs while the answer is grounded in nearby equivalent docs.

Affected queries:
- `hermes_02_configuration_system_prompt`
- `hermes_04_agents`
- `hermes_08_json_mode`

Note: Hermes answers were often grounded in valid Hermes model cards, but not always the exact benchmark URL/version expected.

### 5. Generation issue
Definition: retrieval and routing were adequate, but the produced answer was empty or fallback-like for generation reasons.

Affected queries:
- None as a primary root cause.

## Failed query analysis

### `anthropic_03_configuration_org`
- Root cause: **missing documentation coverage** / **retrieval miss**
- Why it failed: route and provider were correct, but returned sources were `devcontainer`, `web-quickstart`, `setup`, `overview`, and `server-managed-settings`. The expected `admin-setup` URL did not appear.
- Likely fix: strengthen indexing/retrieval coverage for `https://code.claude.com/docs/en/admin-setup`, or relax benchmark to allow equivalent org-setup docs if that page is intentionally summarized through nearby pages.

### `openai_02_configuration_basic`
- Root cause: **missing documentation coverage** / **retrieval miss**
- Why it failed: answer was reasonable and Codex-specific, but sources came from `app/settings`, `codex-manual`, `quickstart`, and `cli`, not from `config-basic` or `config-reference`.
- Likely fix: ensure Codex config pages are indexed and retrievable; if already indexed, improve ranking for config-focused questions.

### `openai_06_permissions`
- Root cause: **missing documentation coverage** / **retrieval miss**
- Why it failed: answer used Codex security/sandbox docs and `agent-approvals-security`, but not the exact `codex/permissions` page.
- Likely fix: add or promote `https://developers.openai.com/codex/permissions` in retrieval candidates for permission queries.

### `hermes_02_configuration_system_prompt`
- Root cause: **benchmark expectation issue** plus **documentation coverage mismatch**
- Why it failed: route/provider were correct and the answer was grounded in Hermes model cards, but sources came from Hermes 3 variants (`70B-FP8`, `70B`, `8B`, `8B-GGUF`) instead of the expected `Hermes-4.3-36B` page.
- Likely fix: either broaden benchmark acceptance to equivalent Hermes model-card URLs, or add more direct retrieval weight toward the exact expected model family.

### `hermes_04_agents`
- Root cause: **benchmark expectation issue** plus **documentation coverage mismatch**
- Why it failed: the system answered from Hermes docs about agentic capabilities, but sources were `Hermes-3-Llama-3.1-70B-FP8` and `Hermes-3-Llama-3.1-8B-GGUF`, not the expected `8B` / `4.3-36B` URLs.
- Likely fix: allow semantically equivalent Hermes variant pages in benchmark, or retarget the query to one exact documented model variant.

### `hermes_05_mcp_tools`
- Root cause: **routing/classifier miss**
- Why it failed: response route was `fallback_no_answer`, provider hit was false, and no sources were returned. The query did not stay on Hermes retrieval at all.
- Likely fix: improve Hermes provider detection for "external tools", "MCP-style", and "integrations" phrasing.

### `hermes_06_permissions_safety`
- Root cause: **routing/classifier miss**
- Why it failed: same failure pattern as above: `fallback_no_answer`, no sources, no provider hit.
- Likely fix: improve classifier support for Hermes safety / permission / tool-calling vocabulary.

### `hermes_07_troubleshooting_quantization`
- Root cause: **routing/classifier miss**
- Why it failed: the system did not connect the query to Hermes model selection or quantization; it fell back with no sources.
- Likely fix: add Hermes-specific query patterns for `quantization`, `GGUF`, `lighter local deployment`, `variant`, `FP8`, `14B`, `70B`.

### `hermes_08_json_mode`
- Root cause: **benchmark expectation issue** plus **documentation coverage mismatch**
- Why it failed: answer was grounded in Hermes docs about JSON mode, but the sources came from Hermes 2 / Hermes 3.2 model cards instead of the benchmark’s exact expected pages.
- Likely fix: either broaden benchmark URL acceptance across equivalent Hermes model cards, or constrain the query to the exact model family expected.

### `hermes_09_reasoning`
- Root cause: **routing/classifier miss**
- Why it failed: route became `comparison_direct` instead of `docs_rag`; the system replied with a clarification-style comparison answer and no sources.
- Likely fix: improve routing so model-variant comparison questions with explicit provider mention still go to retrieval.

### `hermes_10_comparison_variants`
- Root cause: **routing/classifier miss**
- Why it failed: same as above. The explicit comparison was handled as `comparison_direct` with no retrieval.
- Likely fix: route provider-internal model comparisons to `docs_rag` when exact variants are named.

### `openclaw_01_install`
- Root cause: **missing documentation coverage** / **retrieval miss**
- Why it failed: answer was grounded in OpenClaw docs, but sources came from `help/faq-first-run`, `install/node`, and `platforms/mac/dev-setup`, not `docs.openclaw.ai/install`.
- Likely fix: promote `install` landing page in retrieval or ingest it more effectively if chunking/indexing underrepresents it.

### `openclaw_02_setup`
- Root cause: **missing documentation coverage** / **retrieval miss**
- Why it failed: answer relied on FAQ/setup-adjacent docs, not the expected `start/setup` or `cli/setup` pages.
- Likely fix: index and/or boost `start/setup` and `cli/setup` for post-install setup questions.

### `openclaw_03_configuration`
- Root cause: **missing documentation coverage** / **retrieval miss**
- Why it failed: answer referenced `help/faq` and adjacent docs rather than `cli/config` or `gateway/configuration-reference`.
- Likely fix: improve retrieval ranking for direct config pages on generic "configure OpenClaw" queries.

### `openclaw_07_multi_agent`
- Root cause: **missing documentation coverage** / **retrieval miss**
- Why it failed: answer was good and OpenClaw-specific, but sources came from `gateway/config-agents`, `cli/agents`, and `channel-routing`, not `concepts/multi-agent`.
- Likely fix: either ingest/boost `concepts/multi-agent` more strongly or relax the benchmark to accept operationally equivalent multi-agent routing docs.

### `openclaw_09_troubleshooting`
- Root cause: **missing documentation coverage** / **retrieval miss**
- Why it failed: answer came from general diagnostic and browser docs, not the expected automation/help troubleshooting pages.
- Likely fix: boost automation-troubleshooting pages for automation-specific queries.

## Ranked fixes by impact

### 1. Improve documentation coverage and exact-page retrievability for benchmark target URLs
Highest impact.

Why:
- Most failures are `source_miss` with correct provider and correct route.
- This affects Claude Code, Codex, Hermes, and OpenClaw.

Likely actions:
- verify that all expected URLs are fully indexed
- re-ingest missing pages
- inspect chunk quality for landing/config pages
- boost canonical setup/config/troubleshooting pages during retrieval

Expected impact:
- biggest increase in **source hit rate**
- moderate increase in answer quality and trustworthiness

### 2. Fix Hermes routing/classification for tooling, quantization, and model-comparison phrasing
Second-highest impact.

Why:
- Hermes accounts for all hard route/provider misses.
- Several Hermes queries never reached `docs_rag`.

Likely actions:
- add Hermes examples covering MCP/tool use, structured output, quantization, local variants, FP8/GGUF, and direct model-vs-model comparison
- route provider-explicit model comparisons to retrieval instead of `comparison_direct`

Expected impact:
- strong improvement in **provider hit rate** and **route match rate**
- removes low-latency false-direct answers with zero sources

### 3. Revisit benchmark strictness for Hermes and some OpenClaw queries
Medium impact.

Why:
- several failures have correct provider and semantically correct answers, but benchmark expects one exact URL while the system returns a closely related equivalent doc.

Likely actions:
- allow equivalence sets for model-card families
- allow multiple accepted source URLs for operationally equivalent pages

Expected impact:
- improves measured source hit rate without touching product code
- reduces false negatives in evaluation

### 4. Investigate retrieval ranking for generic setup/configuration questions
Medium impact.

Why:
- generic wording often lands on FAQ or neighboring pages instead of the intended canonical config page.

Likely actions:
- review BM25/vector balance for generic setup/config queries
- adjust benchmark wording where needed to better target canonical pages

Expected impact:
- improves consistency across OpenClaw/Codex/Claude setup questions

### 5. Generation changes
Low impact.

Why:
- no clear evidence that generation is the main issue in this run.

Likely actions:
- none recommended before fixing coverage/routing.

## Recommended next step

1. First, verify indexing and retrievability of all benchmark target URLs for Claude Code, Codex, Hermes, and OpenClaw.
2. Second, fix Hermes routing so explicit Hermes model/tool queries always go to `docs_rag`.
3. Third, tighten the benchmark by distinguishing:
   - exact-page expectation
   - equivalent-page acceptance

That ordering should yield the fastest measurable improvement in the next evaluation pass.

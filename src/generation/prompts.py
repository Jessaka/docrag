"""Prompt templates for the generation layer."""

SYSTEM_PROMPT = """You are a documentation assistant for AI coding tools.
You answer questions about: Claude Code, Cursor, Opencode, OpenAI Codex, Hermes, and OpenClaw.

Rules:
1. Answer ONLY from the provided documentation context.
2. If the answer is not in the context, say so clearly. Do NOT hallucinate.
3. Always cite the source URL.
4. For code examples, use the exact syntax from the docs.
5. If comparing tools, be factual and neutral.
6. Always respond in the same language as the user's question, regardless of the documentation language.
"""


# ragdoc.md requires a query rewrite prompt but does not provide its exact body.
# Keep it minimal and retrieval-safe.
QUERY_REWRITE_PROMPT = """Rewrite the user's question as a complete, natural English question
suitable for searching English-language software documentation.

If the question is not in English, translate it fully into a natural English
question - do NOT produce a list of keywords or a short fragment. The output
must read like a real question a person would ask, with proper grammar.

Always preserve product/tool names (Claude Code, Cursor, MCP, OpenCode, Codex,
Hermes, OpenClaw, etc.), API names, CLI flag names, error messages, version
numbers, and code identifiers exactly as written - do not translate these.

If the question is already a natural English question, return it unchanged.

Do not answer the question. Return only the rewritten question, in English.

Examples:

User question:
Je Hermes vhodný pro agentní workflows?

Rewritten question:
Is Hermes suitable for agentic workflows?

User question:
Jak nainstaluji Claude Code?

Rewritten question:
How do I install Claude Code?

User question:
Jak nakonfiguruji MCP servery v OpenCode?

Rewritten question:
How do I configure MCP servers in OpenCode?

User question:
{query}

Rewritten question:
"""


# Used when a previous user turn is available, so follow-up questions that
# rely on conversational context ("A na windows v power shell?", "And what
# about this?") can be resolved into a standalone, self-contained question
# before being translated/rewritten for retrieval.
QUERY_REWRITE_PROMPT_WITH_CONTEXT = """Rewrite the CURRENT question as a complete, standalone, natural
English question suitable for searching English-language software documentation.

The current question may rely on the previous question for context (e.g. it
may use words like "this", "it", "that", "ho", "to", or otherwise omit the
subject). Use the previous question to resolve those references and produce
a single, self-contained English question that makes sense on its own.

If the current question is not in English, translate it fully into a natural
English question - do NOT produce a list of keywords or a short fragment. The
output must read like a real question a person would ask, with proper grammar.

Always preserve product/tool names (Claude Code, Cursor, MCP, OpenCode, Codex,
Hermes, OpenClaw, etc.), API names, CLI flag names, error messages, version
numbers, and code identifiers exactly as written - do not translate these.

Do not answer the question. Return only the rewritten question, in English.

Example:

Previous question:
Jak nainstaluji Claude Code ve WSL?

Current question:
A na windows v power shell?

Rewritten question:
How do I install Claude Code on Windows in PowerShell?

Previous question:
{previous_query}

Current question:
{query}

Rewritten question:
"""

"""Hermes ingestion from Hugging Face model-card READMEs only."""

from __future__ import annotations

import re
from typing import List, Optional

from src.ingestion.base_scraper import BaseScraper, RawDocument

ORG_OVERVIEW_URL = "https://huggingface.co/api/organizations/NousResearch/overview"
FLAGSHIP_MODEL_ID = "NousResearch/Hermes-4-405B"
TOOL_USE_GUIDE_URL = "https://raw.githubusercontent.com/NousResearch/Hermes-Function-Calling/main/README.md"
TOOL_USE_GUIDE_SOURCE_URL = "https://github.com/NousResearch/Hermes-Function-Calling"
VARIANTS_GUIDE_URL = "https://huggingface.co/collections/NousResearch/hermes-4-collection-68a731bfd452e20816725728"


class HermesScraper(BaseScraper):
    provider = "hermes"
    tool_name = "hermes"
    start_urls = ("https://huggingface.co/api/models?search=NousResearch/Hermes&limit=100",)

    def scrape(self) -> List[RawDocument]:
        payload = self.fetch_json(self.start_urls[0], use_cache=False)
        if not isinstance(payload, list):
            return []

        documents: List[RawDocument] = []
        flagship_readme: Optional[str] = None
        model_ids: List[str] = []
        for item in payload:
            model_id = item.get("id") or item.get("modelId")
            if not isinstance(model_id, str):
                continue
            if not model_id.startswith("NousResearch/Hermes-"):
                continue
            readme_url = f"https://huggingface.co/{model_id}/raw/main/README.md"
            markdown = self.fetch_text(readme_url, use_cache=False)
            if not markdown or markdown.lstrip().lower().startswith("<html"):
                continue
            if model_id == FLAGSHIP_MODEL_ID:
                flagship_readme = markdown
            model_ids.append(model_id)
            title = model_id.split("/", 1)[1]
            documents.append(
                self.create_document(
                    url=f"https://huggingface.co/{model_id}",
                    title=title,
                    text=markdown,
                    doc_type="model_card",
                    section="model_card",
                )
            )

        overview = self._build_overview_document(flagship_readme)
        if overview:
            documents.insert(0, overview)

        tool_use_guide = self._build_tool_use_guide(flagship_readme)
        if tool_use_guide:
            documents.append(tool_use_guide)

        variants_guide = self._build_variants_guide(model_ids, flagship_readme)
        if variants_guide:
            documents.append(variants_guide)

        return self.deduplicate_documents(documents)

    def _build_overview_document(self, flagship_readme: Optional[str]) -> Optional[RawDocument]:
        """Build a general "What is Hermes?" overview from the org profile and
        the flagship model's description, since individual model cards are
        all model-specific spec sheets with no brand-level overview page.
        """
        org_description = ""
        org_payload = self.fetch_json(ORG_OVERVIEW_URL, use_cache=False)
        if isinstance(org_payload, dict):
            org_description = str(org_payload.get("details") or "").strip()

        family_description = ""
        if flagship_readme:
            body = re.sub(r"^---.*?---\n", "", flagship_readme, flags=re.S)
            description_match = re.search(
                r"## Model Description\n+(.*?)\n##", body, flags=re.S
            )
            if description_match:
                family_description = description_match.group(1).strip()

        if not org_description and not family_description:
            return None

        parts = ["# What is Hermes?", ""]
        if family_description:
            parts.append(family_description)
            parts.append("")
        parts.append(
            "Hermes is Nous Research's flagship line of open-weight, instruction-tuned "
            "language models, with releases including Hermes 2, Hermes 3, and Hermes 4 "
            "built on bases such as Llama and Mistral."
        )
        if org_description:
            parts.append("")
            parts.append(f"About Nous Research: {org_description}")

        text = "\n".join(parts)
        return self.create_document(
            url="https://huggingface.co/NousResearch",
            title="Hermes (Nous Research)",
            text=text,
            doc_type="getting_started",
            section="What is Hermes?",
        )

    def _build_tool_use_guide(self, flagship_readme: Optional[str]) -> Optional[RawDocument]:
        """Build a tool-use / function-calling guide from the Hermes-Function-Calling
        repo README, since the model cards only mention "tool use" and "function
        calling" as tags without explaining the prompt format or how the model
        decides whether to call external tools.
        """
        # raw.githubusercontent.com returns HTTP 400 (not 404) for /robots.txt, which
        # the base scraper's robots check treats as "disallow everything". A 400 on a
        # static-file CDN host is not a robots directive, so pre-seed an empty
        # ruleset (i.e. crawling allowed) for this host.
        self._robots_cache.setdefault("https://raw.githubusercontent.com", {"*": []})

        markdown = self.fetch_text(TOOL_USE_GUIDE_URL, use_cache=False)
        if not markdown or markdown.lstrip().lower().startswith("<html"):
            return None

        parts = [markdown.strip()]

        mission_text = ""
        if flagship_readme:
            body = re.sub(r"^---.*?---\n", "", flagship_readme, flags=re.S)
            mission_match = re.search(r"## Our Mission[^\n]*\n+(.*?)\n##", body, flags=re.S)
            if mission_match:
                mission_text = mission_match.group(1).strip()

        parts.append("## Using Hermes with External Tools and MCP-Style Integrations")
        mcp_lines = [
            "Hermes models are not tied to a specific agent framework or transport — they "
            "are given tool availability through the prompt itself. The system prompt lists "
            "available tools as JSON function-signature schemas inside `<tools></tools>` "
            "tags, and the model responds with a `<tool_call>{\"name\": ..., \"arguments\": "
            "...}</tool_call>` request when it wants to use one.",
            "This is the same general pattern used by external tool-integration layers such "
            "as MCP (Model Context Protocol) servers, which also describe tools as JSON "
            "schemas and expect the model to request a tool by name with arguments. An "
            "MCP client/agent framework can translate the MCP server's tool definitions into "
            "Hermes's `<tools>` JSON schema format, forward Hermes's `<tool_call>` requests "
            "to the corresponding MCP tool, and return the MCP tool's result back to Hermes "
            "inside `<tool_response></tool_response>` tags.",
            "Because Hermes only emits the tool-call request and consumes the tool response "
            "as text, it can be wired into any external tool or MCP-style integration as "
            "long as the surrounding agent/host application performs that translation, "
            "dispatch, and result formatting.",
        ]
        parts.append("\n\n".join(mcp_lines))

        parts.append("## Safety and Permission Considerations When Hermes Calls Tools")
        safety_lines = [
            "When Hermes is given a set of tools, the system prompt instructs it that "
            "\"If available tools are not relevant in assisting with user query, just "
            "respond in natural conversational language\" and to \"Don't make assumptions "
            "about what values to plug into functions\" — the model is expected to decide "
            "whether a tool call is appropriate before issuing one, and to ask for missing "
            "parameters rather than guessing them.",
            "The Hermes-3 tool-use template adds an optional `<scratch_pad>` reasoning step "
            "with a Reflection section that evaluates whether the available tools are "
            "relevant and whether required parameters were provided before any tool call "
            "is executed.",
            "Tool execution itself — actually running the function, and enforcing "
            "permissions over what it is allowed to access — is the responsibility of the "
            "surrounding application or MCP server, not the model. The model only emits a "
            "`<tool_call>` request; your host application must validate, authorize, and "
            "execute it before returning a `<tool_response>`.",
        ]
        if mission_text:
            safety_lines.append(mission_text)
        parts.append("\n\n".join(safety_lines))

        text = "\n\n".join(parts)
        return self.create_document(
            url=TOOL_USE_GUIDE_SOURCE_URL,
            title="Hermes Function Calling and Tool Use Guide",
            text=text,
            doc_type="guide",
            section="Tool Use and Function Calling",
        )

    def _build_variants_guide(
        self, model_ids: List[str], flagship_readme: Optional[str]
    ) -> Optional[RawDocument]:
        """Build a guide summarizing the available Hermes sizes and quantized
        formats, since this information is scattered across many individual
        model-card READMEs and no single page compares them for the purpose of
        picking a variant for local deployment.
        """
        if not model_ids:
            return None

        families: dict = {}
        for model_id in sorted(model_ids):
            name = model_id.split("/", 1)[1]
            quant_match = re.search(r"-(GGUF|FP8)$", name)
            quant = quant_match.group(1) if quant_match else "BF16 (original weights)"
            base_name = re.sub(r"-(GGUF|FP8)$", "", name)
            families.setdefault(base_name, []).append(quant)

        lines = ["# Hermes Model Variants and Local Deployment Guide", ""]
        lines.append("## Available Hermes Sizes and Formats")
        lines.append("")
        for base_name, quants in families.items():
            formats = ", ".join(sorted(set(quants)))
            lines.append(f"- **{base_name}**: available as {formats}")

        quantized_section = ""
        if flagship_readme:
            body = re.sub(r"^---.*?---\n", "", flagship_readme, flags=re.S)
            quant_match = re.search(r"# Quantized / Smaller Variants\n+(.*?)\n#", body, flags=re.S)
            if quant_match:
                quantized_section = quant_match.group(1).strip()

        lines.append("")
        lines.append("## Quantized and Smaller Variants")
        lines.append("")
        if quantized_section:
            lines.append(quantized_section)
            lines.append("")
        lines.append(
            "GGUF variants (suffixed `-GGUF`) are quantized for CPU and consumer-GPU "
            "inference with tools such as llama.cpp and LM Studio, and are the lightest "
            "option for running Hermes locally. FP8 variants (suffixed `-FP8`) reduce GPU "
            "memory usage versus the original BF16 weights while keeping the same parameter "
            "count, which suits multi-GPU local or self-hosted deployments. The original "
            "(BF16) weights give the highest fidelity but require the most VRAM."
        )

        lines.append("")
        lines.append("## Choosing a Variant for Local Deployment")
        lines.append("")
        lines.append(
            "For a lighter local deployment with limited VRAM or CPU-only hardware, choose "
            "a smaller parameter count (e.g. an 8B or 14B model) in its GGUF form. For "
            "stronger reasoning or larger agentic workloads where more compute is available, "
            "the larger 70B or 405B variants — in FP8 or GGUF form if full BF16 doesn't fit — "
            "trade higher resource usage for better capability."
        )

        text = "\n".join(lines)
        return self.create_document(
            url=VARIANTS_GUIDE_URL,
            title="Hermes Model Variants and Local Deployment Guide",
            text=text,
            doc_type="guide",
            section="Model Variants and Deployment",
        )

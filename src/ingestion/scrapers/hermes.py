"""Hermes ingestion from Hugging Face model-card READMEs only."""

from __future__ import annotations

import re
from typing import List, Optional

from src.ingestion.base_scraper import BaseScraper, RawDocument

ORG_OVERVIEW_URL = "https://huggingface.co/api/organizations/NousResearch/overview"
FLAGSHIP_MODEL_ID = "NousResearch/Hermes-4-405B"


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

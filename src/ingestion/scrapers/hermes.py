"""Hermes ingestion from Hugging Face model-card READMEs only."""

from __future__ import annotations

from typing import List

from src.ingestion.base_scraper import BaseScraper, RawDocument


class HermesScraper(BaseScraper):
    provider = "hermes"
    tool_name = "hermes"
    start_urls = ("https://huggingface.co/api/models?search=NousResearch/Hermes&limit=100",)

    def scrape(self) -> List[RawDocument]:
        payload = self.fetch_json(self.start_urls[0], use_cache=False)
        if not isinstance(payload, list):
            return []

        documents: List[RawDocument] = []
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
        return self.deduplicate_documents(documents)

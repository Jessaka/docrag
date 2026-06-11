"""OpenClaw ingestion from llms-full.txt."""

from __future__ import annotations

from typing import List

from src.ingestion.base_scraper import BaseScraper, RawDocument


class OpenClawScraper(BaseScraper):
    provider = "openclaw"
    tool_name = "openclaw"
    start_urls = ("https://docs.openclaw.ai/llms-full.txt",)

    def scrape(self) -> List[RawDocument]:
        source_url = self.start_urls[0]
        content = self.fetch_text(source_url, use_cache=False)
        if not content:
            return []

        documents: List[RawDocument] = []
        for entry in self.parse_llms_full_documents(content, base_url=source_url):
            url = entry["url"]
            title = entry["title"]
            text = entry["text"]
            section = entry["section"]
            if not self.is_english_url(url) or self.is_excluded_doc_url(url):
                continue
            documents.append(
                self.create_document(
                    url=url,
                    title=title,
                    text=text,
                    doc_type=self.classify_doc_type(url, title, text),
                    section=section,
                )
            )
        return self.deduplicate_documents(documents)

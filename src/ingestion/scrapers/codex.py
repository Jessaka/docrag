"""OpenAI Codex ingestion from developers.openai.com codex docs."""

from __future__ import annotations

from typing import List

from src.ingestion.base_scraper import BaseScraper, RawDocument


class CodexScraper(BaseScraper):
    provider = "openai"
    tool_name = "codex"
    start_urls = ("https://developers.openai.com/llms-full.txt",)
    codex_index_url = "https://developers.openai.com/codex/llms.txt"

    def scrape(self) -> List[RawDocument]:
        # Validate the approved source exists.
        root_export = self.fetch_text(self.start_urls[0], use_cache=False)
        if not root_export:
            return []

        index_text = self.fetch_text(self.codex_index_url, use_cache=False)
        if not index_text:
            return []

        entries = self.parse_llms_index(index_text, base_url=self.codex_index_url)
        documents: List[RawDocument] = []
        for entry in entries:
            url = entry["url"]
            if "/codex/" not in url:
                continue
            markdown_text = self.fetch_text(url, use_cache=False)
            if not markdown_text or markdown_text.lstrip().lower().startswith("<html"):
                continue
            document = self.create_document(
                url=url.replace(".md", ""),
                title=entry["title"],
                text=markdown_text,
                doc_type=self.classify_doc_type(url, entry["title"], markdown_text),
                section=entry["section"] or entry["title"],
            )
            documents.append(document)
        return self.deduplicate_documents(documents)

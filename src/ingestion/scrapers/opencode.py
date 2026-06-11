"""Opencode ingestion sourced from sitemap.xml (English docs only)."""

from __future__ import annotations

from typing import List, Set

from src.ingestion.base_scraper import BaseScraper, RawDocument


class OpencodeScraper(BaseScraper):
    provider = "opencode"
    tool_name = "opencode"
    start_urls = ("https://opencode.ai/sitemap.xml",)

    def scrape(self) -> List[RawDocument]:
        sitemap_text = self.fetch_text(self.start_urls[0], use_cache=False)
        if not sitemap_text:
            return []

        urls = self.extract_urls_from_sitemap(sitemap_text)
        filtered: List[str] = []
        seen: Set[str] = set()
        for url in urls:
            path = self.canonicalize_url(url)
            if path in seen:
                continue
            seen.add(path)
            parsed_path = url.lower()
            if "/docs" not in parsed_path:
                continue
            if not self.is_english_url(url) or self.is_excluded_doc_url(url):
                continue
            filtered.append(url)

        documents: List[RawDocument] = []
        for url in filtered[: self.max_pages]:
            html = self.fetch_html(url, use_cache=False)
            if not html:
                continue
            parsed = self.parse_main_content(url, html)
            text = str(parsed["text"])
            title = str(parsed["title"])
            if len(text.split()) < 40:
                continue
            documents.append(
                self.create_document(
                    url=url,
                    title=title,
                    text=text,
                    doc_type=self.classify_doc_type(url, title, text),
                    section=str(parsed["section"]),
                )
            )
        return self.deduplicate_documents(documents)

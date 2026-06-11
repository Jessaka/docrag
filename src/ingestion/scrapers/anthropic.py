"""Anthropic / Claude Code ingestion from code.claude.com llms index."""

from __future__ import annotations

import re
from typing import List

from src.ingestion.base_scraper import BaseScraper, RawDocument


class AnthropicScraper(BaseScraper):
    provider = "anthropic"
    tool_name = "claude-code"
    start_urls = ("https://code.claude.com/docs/llms.txt",)

    def scrape(self) -> List[RawDocument]:
        index_url = self.start_urls[0]
        index_text = self.fetch_text(index_url, use_cache=False)
        if not index_text:
            return []

        documents: List[RawDocument] = []
        entries = self.parse_llms_index(index_text, base_url=index_url)
        for entry in entries:
            title = entry["title"]
            url = entry["url"]
            section = entry["section"] or title
            if not url.endswith(".md"):
                continue
            if "/en/" not in url:
                continue
            if not self.is_english_url(url) or self.is_excluded_doc_url(url):
                continue

            markdown_text = self.fetch_text(url, use_cache=False)
            if not markdown_text or markdown_text.lstrip().lower().startswith("<html"):
                continue

            normalized_url = url.lower().replace('.md', '')
            install_paths = (
                '/en/setup',
                '/en/quickstart',
                '/en/overview',
                '/en/desktop-quickstart',
                '/en/web-quickstart',
                '/en/troubleshoot-install',
            )
            if normalized_url.endswith(install_paths):
                markdown_text = (
                    "Instalace Claude Code. Jak nainstalovat Claude Code. Claude Code setup. "
                    "How to install Claude Code. Claude Code installation instructions.\n\n"
                    + markdown_text
                )

            for section_title, section_text in self.split_markdown_sections(markdown_text):
                document_url = url[:-3]
                if section_title and section_title != "overview":
                    slug = re.sub(r'[^a-z0-9]+', '-', section_title.lower()).strip('-')
                    if slug:
                        document_url = f"{document_url}#{slug}"
                document = self.create_document(
                    url=document_url,
                    title=title,
                    text=section_text,
                    doc_type=self.classify_doc_type(url, title, section_text),
                    section=section_title or section,
                )
                documents.append(document)
        return self.deduplicate_documents(documents)

    def split_markdown_sections(self, markdown_text: str) -> List[tuple[str, str]]:
        """Split a markdown page into section-level documents by H2 headings."""
        cleaned = markdown_text.strip()
        parts = re.split(r'(?m)^##\s+', cleaned)
        if len(parts) <= 1:
            return [("overview", cleaned)]

        sections: List[tuple[str, str]] = []
        preamble = parts[0].strip()
        if preamble:
            sections.append(("overview", preamble))

        for part in parts[1:]:
            lines = part.splitlines()
            if not lines:
                continue
            heading = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            if not body:
                continue
            sections.append((heading, f"## {heading}\n\n{body}"))
        return sections or [("overview", cleaned)]

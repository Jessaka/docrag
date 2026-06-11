"""Cursor ingestion sourced from sitemap plus docs navigation."""

from __future__ import annotations

import html
import re
from typing import List, Set

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from src.ingestion.base_scraper import BaseScraper, RawDocument


class CursorScraper(BaseScraper):
    provider = "cursor"
    tool_name = "cursor"
    start_urls = ("https://cursor.com/sitemap.xml",)
    docs_root = "https://docs.cursor.com"

    def scrape(self) -> List[RawDocument]:
        sitemap_text = self.fetch_text(self.start_urls[0], use_cache=False)
        if not sitemap_text:
            return []

        sitemap_urls = self.extract_urls_from_sitemap(sitemap_text)
        candidate_urls: List[str] = []
        for url in sitemap_urls:
            if "/blog" in url or "/pricing" in url or "/terms" in url or "/privacy" in url:
                continue
            if "/docs/" in url:
                candidate_urls.append(url)

        # The approved sitemap currently does not expose the actual docs URLs.
        # Use the docs root to discover /docs/ pages only.
        docs_root_html = self.fetch_text(self.docs_root, use_cache=False)
        if docs_root_html:
            discovered = self._extract_links(self.docs_root, docs_root_html)
            candidate_urls.extend([url for url in discovered if "/docs/" in url])
            route_matches = re.findall(r'filePath\\":\\"(/docs/[^\\"]+)\\"', docs_root_html)
            candidate_urls.extend([f"https://cursor.com{match}" for match in route_matches])

        deduped_urls = []
        seen: Set[str] = set()
        for url in candidate_urls:
            normalized = self.canonicalize_url(url)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped_urls.append(normalized)

        documents: List[RawDocument] = []
        for url in deduped_urls[: max(self.max_pages, 80)]:
            if self.is_excluded_doc_url(url) or not self.is_english_url(url):
                continue
            if url.endswith('.mdx') or url.endswith('.md'):
                continue
            rendered = self.render_page(url)
            if not rendered:
                continue
            title = rendered["title"]
            text = rendered["text"]
            section = rendered["section"]
            if len(text.split()) < 80:
                continue
            document = self.create_document(
                url=url,
                title=title,
                text=text,
                doc_type=self.classify_doc_type(url, title, text),
                section=section,
            )
            documents.append(document)
        return self.deduplicate_documents(documents)

    def render_page(self, url: str) -> dict | None:
        """Render a Cursor docs page with Playwright and extract the main body."""
        if not self._is_allowed_by_robots(url):
            return None
        self._respect_rate_limit(url)

        html_text = self.fetch_html(url, use_cache=False)
        if not html_text:
            return None

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, channel="chrome")
                page = browser.new_page()
                try:
                    page.goto(url, wait_until="networkidle", timeout=90000)
                    selectors = ["main .prose", "main article", "article", "main"]
                    body_text = ""
                    for selector in selectors:
                        locator = page.locator(selector)
                        if locator.count() == 0:
                            continue
                        candidate = locator.first.inner_text(timeout=5000).strip()
                        if len(candidate.split()) > len(body_text.split()):
                            body_text = candidate
                    if body_text:
                        title = page.title().strip()
                        section = title.split("|", 1)[0].strip() if title else url
                        return {
                            "title": title or url,
                            "section": section or url,
                            "text": body_text,
                        }
                finally:
                    browser.close()
        except Exception:
            pass

        return self.extract_shell_content(url, html_text)

    def extract_shell_content(self, url: str, html_text: str) -> dict | None:
        """Fallback extraction from server-rendered RSC shell when browser automation is unavailable."""
        title_match = re.search(r'<title>(.*?)</title>', html_text, flags=re.IGNORECASE | re.DOTALL)
        title = html.unescape(title_match.group(1)).strip() if title_match else url
        description_match = re.search(r'<meta name="description" content="([^"]+)"', html_text, flags=re.IGNORECASE)
        description = html.unescape(description_match.group(1)).strip() if description_match else ""

        raw_parts = re.findall(r'children\\":\\"(.*?)\\"', html_text)
        cleaned_parts: List[str] = []
        seen: Set[str] = set()
        for raw in raw_parts:
            try:
                decoded = raw.encode('utf-8').decode('unicode_escape', errors='ignore')
            except Exception:
                decoded = raw
            text = html.unescape(decoded).strip()
            if not text or text in seen:
                continue
            lowered = text.lower()
            if lowered.startswith(("$", "function(", "(function", "window.")):
                continue
            if any(fragment in lowered for fragment in ("googletagmanager", "gtag(", "this page could not be found", "this page was not found", "return home", "report an issue")):
                continue
            if any(fragment in text for fragment in ("document.documentElement", "window.navigator", "gtag('js'", "googletagmanager.com")):
                continue
            if len(text) < 3:
                continue
            seen.add(text)
            cleaned_parts.append(text)

        text_blocks: List[str] = []
        if title:
            text_blocks.append(title)
        if description:
            text_blocks.append(description)
        text_blocks.extend(cleaned_parts)
        merged = "\n\n".join(text_blocks).strip()
        if len(merged.split()) < 80:
            return None

        section = title.split("|", 1)[0].strip() if title else url
        return {
            "title": title or url,
            "section": section or url,
            "text": merged,
        }

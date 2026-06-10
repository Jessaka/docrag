"""Base scraper primitives for ingestion."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Sequence, Set
from urllib import parse, request

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "ai-docs-chatbot/1.0 (educational project)"
DEFAULT_RATE_LIMIT_SECONDS = 0.5  # max 2 req/sec per domain
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_PAGES = 50
DEFAULT_CACHE_DIR = "/tmp/ai-docs-chatbot-html-cache"


@dataclass
class RawDocument:
    """Raw scraped document before chunking."""

    text: str
    url: str
    title: str
    provider: str
    tool_name: str
    doc_type: str
    section: str
    chunk_index: int = 0
    version: Optional[str] = None
    last_crawled: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    language: str = "en"
    is_deprecated: bool = False
    code_heavy: bool = False
    raw_html: str = ""

    def to_payload(self) -> Dict[str, object]:
        return {
            "text": self.text,
            "url": self.url,
            "title": self.title,
            "provider": self.provider,
            "tool_name": self.tool_name,
            "doc_type": self.doc_type,
            "section": self.section,
            "chunk_index": self.chunk_index,
            "version": self.version,
            "last_crawled": self.last_crawled,
            "language": self.language,
            "is_deprecated": self.is_deprecated,
            "code_heavy": self.code_heavy,
        }


class _SimpleHTMLExtractor(HTMLParser):
    """Lightweight HTML extractor for links, title, and visible text."""

    def __init__(self):
        super().__init__()
        self.title_parts: List[str] = []
        self.text_parts: List[str] = []
        self.links: List[str] = []
        self.heading_parts: List[str] = []
        self._skip_depth = 0
        self._inside_title = False
        self._inside_heading = False
        self._current_href: Optional[str] = None

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._inside_title = True
        if tag in {"h1", "h2", "h3"}:
            self._inside_heading = True
        if tag == "a":
            self._current_href = attrs_dict.get("href")

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._inside_title = False
        if tag in {"h1", "h2", "h3"}:
            self._inside_heading = False
        if tag == "a":
            self._current_href = None
        if tag in {"p", "div", "section", "article", "main", "li", "pre", "code", "br", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return
        text = unescape(data).strip()
        if not text:
            return
        if self._inside_title:
            self.title_parts.append(text)
        if self._inside_heading:
            self.heading_parts.append(text)
        self.text_parts.append(text)

    def error(self, message: str):
        logger.debug("HTML parse warning: %s", message)


class BaseScraper(ABC):
    """Abstract base scraper with robots, rate limit, and HTML cache."""

    provider: str = ""
    tool_name: str = ""
    start_urls: Sequence[str] = ()
    allowed_domains: Sequence[str] = ()
    max_pages: int = DEFAULT_MAX_PAGES
    user_agent: str = DEFAULT_USER_AGENT
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS
    cache_dir: str = DEFAULT_CACHE_DIR

    def __init__(
        self,
        start_urls: Optional[Sequence[str]] = None,
        max_pages: Optional[int] = None,
        cache_dir: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        self.start_urls = tuple(start_urls or self.start_urls)
        self.max_pages = max_pages or self.max_pages
        self.cache_dir = cache_dir or self.cache_dir
        self.user_agent = user_agent or self.user_agent
        self._robots_cache: Dict[str, Dict[str, List[str]]] = {}
        self._last_request_at: Dict[str, float] = {}
        os.makedirs(self.cache_dir, exist_ok=True)

    @abstractmethod
    def scrape(self) -> List[RawDocument]:
        """Scrape and return raw documents."""

    def fetch_html(self, url: str, use_cache: bool = True) -> Optional[str]:
        """Fetch HTML with robots.txt, rate limiting, and /tmp cache."""
        if use_cache:
            cached = self._read_cached_html(url)
            if cached is not None:
                return cached

        if not self._is_allowed_by_robots(url):
            logger.info("Skipping %s due to robots.txt", url)
            return None

        self._respect_rate_limit(url)
        req = request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                content_type = response.headers.get("Content-Type", "")
                if (
                    "text/html" not in content_type
                    and "text/plain" not in content_type
                    and "application/xhtml+xml" not in content_type
                    and "text/markdown" not in content_type
                ):
                    logger.info("Skipping non-HTML content at %s (%s)", url, content_type)
                    return None
                html = response.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return None

        self._write_cached_html(url, html)
        return html

    def parse_html(self, url: str, html: str) -> Dict[str, object]:
        """Extract title, visible text, links, and section from HTML."""
        parser = _SimpleHTMLExtractor()
        parser.feed(html)
        title = self._clean_text(" ".join(parser.title_parts)) or url
        text = self._clean_text("\n".join(parser.text_parts))
        section = self._clean_text(" | ".join(parser.heading_parts[:3])) or title
        links = self._extract_links(url=url, html=html)
        return {
            "title": title,
            "text": text,
            "section": section,
            "links": links,
        }

    def _extract_links(self, url: str, html: str) -> List[str]:
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
        normalized: List[str] = []
        seen: Set[str] = set()
        for href in hrefs:
            absolute = parse.urljoin(url, href)
            absolute = absolute.split("#", 1)[0]
            absolute = self.normalize_discovered_url(absolute)
            if not absolute:
                continue
            if not absolute.startswith("http"):
                continue
            if not self._is_allowed_domain(absolute):
                continue
            if not self.should_follow_url(absolute):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            normalized.append(absolute)
        return normalized

    def normalize_discovered_url(self, url: str) -> str:
        """Normalize discovered links before enqueueing them."""
        return url

    def should_follow_url(self, url: str) -> bool:
        """Return whether a discovered URL should be crawled."""
        path = (parse.urlparse(url).path or "").lower()
        blocked_suffixes = (
            ".css",
            ".js",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".webp",
            ".xml",
            ".txt",
            ".pdf",
        )
        return not path.endswith(blocked_suffixes)

    def _is_allowed_domain(self, url: str) -> bool:
        hostname = (parse.urlparse(url).hostname or "").lower()
        if not self.allowed_domains:
            return True
        return any(
            hostname == domain.lower() or hostname.endswith(f".{domain.lower()}")
            for domain in self.allowed_domains
        )

    def _is_allowed_by_robots(self, url: str) -> bool:
        parsed = parse.urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots_cache:
            try:
                robots_url = parse.urljoin(base, "/robots.txt")
                req = request.Request(robots_url, headers={"User-Agent": self.user_agent})
                with request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                    robots_text = response.read().decode("utf-8", errors="ignore")
            except Exception as exc:
                logger.warning("Could not read robots.txt for %s: %s", base, exc)
                self._robots_cache[base] = {"*": ["/"]}
                return False
            self._robots_cache[base] = self._parse_robots_txt(robots_text)
        return self._is_path_allowed_by_rules(parsed.path or "/", self._robots_cache[base])

    def _parse_robots_txt(self, robots_text: str) -> Dict[str, List[str]]:
        rules: Dict[str, List[str]] = {}
        current_agents: List[str] = []
        for raw_line in robots_text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = [part.strip() for part in line.split(":", 1)]
            key = key.lower()
            if key == "user-agent":
                agent = value or "*"
                current_agents = [agent]
                rules.setdefault(agent, [])
            elif key == "disallow":
                disallow_path = value.strip()
                for agent in current_agents or ["*"]:
                    rules.setdefault(agent, []).append(disallow_path)
        return rules or {"*": []}

    def _is_path_allowed_by_rules(self, path: str, rules: Dict[str, List[str]]) -> bool:
        candidate_agents = [self.user_agent, "*"]
        for agent in candidate_agents:
            for blocked_prefix in rules.get(agent, []):
                if blocked_prefix in {"", None}:
                    continue
                if blocked_prefix == "/":
                    return False
                if path.startswith(blocked_prefix):
                    return False
        return True

    def _respect_rate_limit(self, url: str) -> None:
        hostname = parse.urlparse(url).netloc
        now = time.monotonic()
        last_request_at = self._last_request_at.get(hostname)
        if last_request_at is not None:
            elapsed = now - last_request_at
            if elapsed < self.rate_limit_seconds:
                time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_at[hostname] = time.monotonic()

    def _cache_file_path(self, url: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{digest}.html")

    def _read_cached_html(self, url: str) -> Optional[str]:
        cache_path = self._cache_file_path(url)
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as file_handle:
                return file_handle.read()
        except Exception as exc:
            logger.warning("Failed to read cached HTML for %s: %s", url, exc)
            return None

    def _write_cached_html(self, url: str, html: str) -> None:
        cache_path = self._cache_file_path(url)
        try:
            with open(cache_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(html)
        except Exception as exc:
            logger.warning("Failed to write cached HTML for %s: %s", url, exc)

    @staticmethod
    def _clean_text(value: str) -> str:
        value = re.sub(r"\r", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        value = re.sub(r"[ \t]{2,}", " ", value)
        return value.strip()


class GenericHTMLDocsScraper(BaseScraper):
    """Generic crawler for HTML documentation sites."""

    default_doc_type: str = "guide"
    same_path_prefix_only: bool = True

    def scrape(self) -> List[RawDocument]:
        if not self.start_urls:
            logger.warning("No start URLs configured for %s", self.__class__.__name__)
            return []

        documents: List[RawDocument] = []
        queue: List[str] = list(self.start_urls)
        visited: Set[str] = set()

        while queue and len(visited) < self.max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            html = self.fetch_html(url)
            if not html:
                continue

            parsed = self.parse_html(url, html)
            text = str(parsed["text"])
            if text:
                documents.append(
                    RawDocument(
                        text=text,
                        url=url,
                        title=str(parsed["title"]),
                        provider=self.provider,
                        tool_name=self.tool_name,
                        doc_type=self.classify_doc_type(url, str(parsed["title"]), text),
                        section=str(parsed["section"]),
                        version=self.extract_version(url, str(parsed["title"]), text),
                        is_deprecated=self.detect_deprecated(text),
                        code_heavy=self.detect_code_heavy(text),
                        raw_html=html,
                    )
                )
                logger.info("Scraped %s", url)

            for link in parsed["links"]:
                if link in visited or link in queue:
                    continue
                if self.same_path_prefix_only and not self._matches_seed_prefix(link):
                    continue
                queue.append(link)

        return documents

    def classify_doc_type(self, url: str, title: str, text: str) -> str:
        haystack = f"{url} {title} {text[:1000]}".lower()
        if any(token in haystack for token in ("api", "reference", "sdk", "parameter", "method")):
            return "api_reference"
        if any(token in haystack for token in ("getting started", "quickstart", "first steps")):
            return "getting_started"
        if any(token in haystack for token in ("changelog", "release notes", "what's new")):
            return "changelog"
        if any(token in haystack for token in ("model card", "benchmark", "context length")):
            return "model_card"
        if any(token in haystack for token in ("config", "configuration", "settings")):
            return "config_reference"
        if any(token in haystack for token in ("faq", "frequently asked")):
            return "faq"
        return self.default_doc_type

    def extract_version(self, url: str, title: str, text: str) -> Optional[str]:
        match = re.search(r"\b(v?\d+\.\d+(?:\.\d+)?)\b", f"{url} {title} {text[:300]}")
        return match.group(1) if match else None

    def detect_deprecated(self, text: str) -> bool:
        lowered = text.lower()
        return "deprecated" in lowered or "no longer supported" in lowered

    def detect_code_heavy(self, text: str) -> bool:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return False
        code_like = sum(
            1
            for line in lines
            if line.startswith(("    ", "\t", "$", "def ", "class ", "import ", "from ", "npm ", "pip "))
            or "```" in line
        )
        return (code_like / len(lines)) > 0.3

    def _matches_seed_prefix(self, link: str) -> bool:
        if not self.start_urls:
            return True
        for seed_url in self.start_urls:
            parsed_seed = parse.urlparse(seed_url)
            parsed_link = parse.urlparse(link)
            if parsed_seed.netloc != parsed_link.netloc:
                continue
            if parsed_link.path.startswith(parsed_seed.path.rstrip("/")):
                return True
        return False

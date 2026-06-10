"""Scraper for Claude Code docs."""

from urllib import parse

from src.ingestion.base_scraper import GenericHTMLDocsScraper


class AnthropicScraper(GenericHTMLDocsScraper):
    provider = "anthropic"
    tool_name = "claude-code"
    start_urls = ("https://docs.anthropic.com/en/docs/claude-code",)
    allowed_domains = ("docs.anthropic.com",)
    default_doc_type = "guide"
    same_path_prefix_only = False

    def normalize_discovered_url(self, url: str) -> str:
        parsed = parse.urlparse(url)
        path = parsed.path
        if parsed.netloc == "docs.anthropic.com" and path.startswith("/docs/en/"):
            path = path.replace("/docs/en/", "/en/", 1)
            parsed = parsed._replace(path=path)
        return parse.urlunparse(parsed)

    def should_follow_url(self, url: str) -> bool:
        if not super().should_follow_url(url):
            return False
        parsed = parse.urlparse(url)
        return parsed.netloc == "docs.anthropic.com" and parsed.path.startswith("/en/")

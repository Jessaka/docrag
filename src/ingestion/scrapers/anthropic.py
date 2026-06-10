"""Scraper for Claude Code docs."""

from src.ingestion.base_scraper import GenericHTMLDocsScraper


class AnthropicScraper(GenericHTMLDocsScraper):
    provider = "anthropic"
    tool_name = "claude-code"
    start_urls = ("https://docs.anthropic.com/en/docs/claude-code",)
    allowed_domains = ("docs.anthropic.com",)
    default_doc_type = "guide"

"""Scraper for OpenAI Codex documentation."""

from src.ingestion.base_scraper import GenericHTMLDocsScraper


class CodexScraper(GenericHTMLDocsScraper):
    provider = "openai"
    tool_name = "codex"
    start_urls = ("https://platform.openai.com/docs",)
    allowed_domains = ("platform.openai.com",)
    default_doc_type = "api_reference"

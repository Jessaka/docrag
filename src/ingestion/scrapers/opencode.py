"""Scraper for Opencode docs and GitHub pages."""

from src.ingestion.base_scraper import GenericHTMLDocsScraper


class OpencodeScraper(GenericHTMLDocsScraper):
    provider = "opencode"
    tool_name = "opencode"
    start_urls = (
        "https://opencode.ai/docs",
        "https://github.com/sst/opencode",
    )
    allowed_domains = (
        "opencode.ai",
        "github.com",
    )
    default_doc_type = "guide"
    same_path_prefix_only = False

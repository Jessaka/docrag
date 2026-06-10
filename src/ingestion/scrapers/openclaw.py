"""Scraper for OpenClaw documentation sources."""

from src.ingestion.base_scraper import GenericHTMLDocsScraper


class OpenClawScraper(GenericHTMLDocsScraper):
    provider = "openclaw"
    tool_name = "openclaw"
    start_urls = ()
    allowed_domains = ()
    default_doc_type = "guide"

    def __init__(self, start_urls=None, **kwargs):
        super().__init__(start_urls=start_urls or self.start_urls, **kwargs)

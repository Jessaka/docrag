"""Scraper for Cursor docs."""

from src.ingestion.base_scraper import GenericHTMLDocsScraper


class CursorScraper(GenericHTMLDocsScraper):
    provider = "cursor"
    tool_name = "cursor"
    start_urls = ("https://docs.cursor.com",)
    allowed_domains = ("docs.cursor.com",)
    default_doc_type = "guide"

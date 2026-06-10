"""Scraper for Hermes documentation sources."""

from src.ingestion.base_scraper import GenericHTMLDocsScraper


class HermesScraper(GenericHTMLDocsScraper):
    provider = "hermes"
    tool_name = "hermes"
    start_urls = (
        "https://huggingface.co/NousResearch",
        "https://github.com/NousResearch",
    )
    allowed_domains = (
        "huggingface.co",
        "github.com",
    )
    default_doc_type = "model_card"
    same_path_prefix_only = False

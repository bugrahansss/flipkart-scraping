"""Scrape Flipkart search results, product details and reviews with Python."""

from .client import REVIEW_SORTS, FlipkartScraper, ScrapeError, clean_product_url, reviews_url, search_url
from .parser import (
    PRODUCT_FIELDS,
    REVIEW_FIELDS,
    SEARCH_FIELDS,
    get_state,
    parse_product,
    parse_reviews,
    parse_search,
)

__all__ = [
    "FlipkartScraper",
    "PRODUCT_FIELDS",
    "REVIEW_FIELDS",
    "REVIEW_SORTS",
    "SEARCH_FIELDS",
    "ScrapeError",
    "clean_product_url",
    "get_state",
    "parse_product",
    "parse_reviews",
    "parse_search",
    "reviews_url",
    "search_url",
]

__version__ = "0.1.0"

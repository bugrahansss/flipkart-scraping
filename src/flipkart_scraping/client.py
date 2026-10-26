"""Fetch Flipkart pages through the Scrape.do API and parse them.

Flipkart rarely blocks a request outright. It serves non-browser user agents
(python-requests, curl) the page with an empty ``window.__INITIAL_STATE__``,
so the data object a scraper needs is missing. Scrape.do returns the full
page with its JSON state, and ``geoCode=in`` keeps the exit IP in India, the
only market Flipkart sells in, for 1 credit per request. ``render=true`` is
deliberately not used: the rendered DOM no longer carries the state script.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote_plus

import requests

from .parser import get_state, parse_card, parse_product, parse_review, product_cards, review_values

API_URL = "https://api.scrape.do/"
TOKEN_ENV = "SCRAPEDO_TOKEN"
BASE_URL = "https://www.flipkart.com"

#: Review sort orders. Each serves up to 20 pages of 10 reviews; running all
#: four and removing duplicates reaches further than any single one.
REVIEW_SORTS = ("MOST_HELPFUL", "MOST_RECENT", "POSITIVE_FIRST", "NEGATIVE_FIRST")

#: Flipkart stops serving search products after page 25 on most queries.
SEARCH_PAGE_CEILING = 25
#: Review pages stop after 20 per sort order.
REVIEW_PAGE_CEILING = 20


class ScrapeError(RuntimeError):
    """Raised when a page cannot be fetched."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def search_url(query: str, page: int = 1, min_price: Optional[int] = None, max_price: Optional[int] = None) -> str:
    """Build a Flipkart search URL, optionally limited to a price band.

    Price bands are how you get past the page ceiling: split a busy search
    into bands, and if a band still reaches the ceiling, halve it.
    """
    url = f"{BASE_URL}/search?q={quote_plus(query)}&page={page}"
    if min_price is not None:
        url += f"&p%5B%5D=facets.price_range.from%3D{int(min_price)}"
    if max_price is not None:
        url += f"&p%5B%5D=facets.price_range.to%3D{int(max_price)}"
    return url


def clean_product_url(url: str) -> str:
    """Drop Flipkart's tracking parameters but keep ``pid`` and ``lid``.

    ``lid`` (listing id) decides which seller's offer the page shows. Keep it
    to get the price the search card advertised; drop it to get the default offer.
    """
    url = url.split("&marketplace")[0]
    return BASE_URL + url if url.startswith("/") else url


def reviews_url(product_url: str) -> str:
    """The reviews URL is the product URL with ``/p/`` swapped for ``/product-reviews/``.

    ``pid`` is kept because it pins the variant the reviews belong to.
    """
    url = clean_product_url(product_url)
    if "/product-reviews/" in url:
        return url
    if "/p/" not in url:
        raise ValueError(f"Not a Flipkart product URL (no /p/ segment): {url}")
    base, _, query = url.partition("?")
    base = base.replace("/p/", "/product-reviews/", 1)
    params = [p for p in query.split("&") if p.startswith("pid=")]
    return base + ("?" + "&".join(params) if params else "")


class FlipkartScraper:
    """Scrape Flipkart search results, product details and reviews.

    >>> scraper = FlipkartScraper(token="YOUR_SCRAPEDO_TOKEN")
    >>> products = scraper.search("laptop", max_pages=3)
    >>> details = scraper.get_product(products[0]["url"])
    >>> reviews = scraper.get_reviews(products[0]["url"])
    """

    def __init__(
        self,
        token: Optional[str] = None,
        geo_code: str = "in",
        timeout: float = 90.0,
        retries: int = 2,
        session: Optional[requests.Session] = None,
    ):
        self.token = token or os.environ.get(TOKEN_ENV, "")
        if not self.token:
            raise ValueError(f"A Scrape.do API token is required. Pass token=... or set {TOKEN_ENV}.")
        self.geo_code = geo_code
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = session or requests.Session()

    # ------------------------------------------------------------------ fetching

    def fetch(self, url: str) -> str:
        """Return the raw HTML of ``url`` (1 Scrape.do credit per request)."""
        params = {"token": self.token, "url": url}
        if self.geo_code:
            params["geoCode"] = self.geo_code
        last_error: Optional[ScrapeError] = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(API_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = ScrapeError(f"Request failed: {exc}")
            else:
                if response.status_code == 200:
                    return response.text
                last_error = ScrapeError(
                    f"Request for {url} failed with status {response.status_code}",
                    status_code=response.status_code,
                )
                # Client errors (bad token, bad URL) will not fix themselves
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < self.retries:
                time.sleep(2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------ search

    def search(
        self,
        query: str,
        max_pages: int = 3,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Search results as rows, one per unique product.

        Sponsored placements repeat the same product on later pages; only the
        first appearance of each product id is kept. The loop stops at the
        first page with no products (Flipkart returns a 200 with an empty
        results area past its ceiling, usually page 25).
        """
        rows: Dict[str, Dict[str, Any]] = {}
        for page in range(1, max(1, max_pages) + 1):
            cards = list(product_cards(get_state(self.fetch(search_url(query, page, min_price, max_price)))))
            if not cards:
                break
            for card in cards:
                row = parse_card(card)
                if row["product_id"] and row["product_id"] not in rows:
                    rows[row["product_id"]] = row
                    if max_items and len(rows) >= max_items:
                        return list(rows.values())
        return list(rows.values())

    # ------------------------------------------------------------------ product

    def get_product(self, url: str) -> Dict[str, Any]:
        """Product details: seller, full specs, star breakdown, delivery date and more."""
        url = clean_product_url(url)
        row = parse_product(get_state(self.fetch(url)))
        row["url"] = url
        return row

    # ------------------------------------------------------------------ reviews

    def get_reviews(
        self,
        product_url: str,
        sorts: Sequence[str] = REVIEW_SORTS,
        max_pages: int = REVIEW_PAGE_CEILING,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Reviews for one product, deduplicated by review id across sort orders.

        Each sort order serves at most 20 pages of 10, so a product with more
        than 200 reviews needs several orders to reach most of them.
        """
        base = reviews_url(product_url)
        sep = "&" if "?" in base else "?"
        rows: Dict[str, Dict[str, Any]] = {}
        for sort in sorts:
            for page in range(1, max(1, max_pages) + 1):
                values = list(review_values(get_state(self.fetch(f"{base}{sep}sortOrder={sort}&page={page}"))))
                if not values:
                    break
                for value in values:
                    row = parse_review(value, found_via=sort)
                    if row["review_id"] and row["review_id"] not in rows:
                        rows[row["review_id"]] = row
                        if max_items and len(rows) >= max_items:
                            return list(rows.values())
        return list(rows.values())


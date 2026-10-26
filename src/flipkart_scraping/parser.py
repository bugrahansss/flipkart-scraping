"""Parse Flipkart pages from the JSON state the site embeds in every page.

Every Flipkart page assigns one JSON object to ``window.__INITIAL_STATE__``
inside a ``<script>`` tag. Reading that object instead of the HTML avoids the
hashed CSS class names, which change with each frontend build and differ
between the list layout (24 cards) and the grid layout (40 cards).

Two state shapes are handled:

* Search pages: ``pageDataV4.page.data`` holds rows of widgets; products are
  ``PRODUCT_SUMMARY`` widgets.
* Product and review pages: ``multiWidgetState``. Prices, ratings and seller
  terms sit in ``pageContext.fdpEventTracking.events.psi``; specifications,
  seller name and delivery date sit in widget label nodes; reviews are
  ``REVIEWS`` widgets.

Note: plain HTTP clients with a default user agent receive the page with an
empty state (``window.__INITIAL_STATE__ = {}``). Fetch pages with a browser
user agent or through Scrape.do.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Iterable, Iterator, List

BASE_URL = "https://www.flipkart.com"
_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*")

SEARCH_FIELDS = [
    "product_id",
    "listing_id",
    "title",
    "subtitle",
    "price",
    "mrp",
    "discount_pct",
    "rating",
    "ratings_count",
    "reviews_count",
    "availability",
    "f_assured",
    "sponsored",
    "key_specs",
    "url",
]

PRODUCT_FIELDS = [
    "product_id",
    "listing_id",
    "title",
    "brand",
    "price",
    "mrp",
    "rating",
    "ratings_count",
    "reviews_count",
    "stars_5",
    "stars_4",
    "stars_3",
    "stars_2",
    "stars_1",
    "aspect_ratings",
    "seller",
    "seller_id",
    "availability",
    "cod",
    "return_policy",
    "delivery_by",
    "offer_count",
    "spec_count",
    "specs",
    "url",
]

REVIEW_FIELDS = [
    "review_id",
    "rating",
    "title",
    "text",
    "created",
    "helpful",
    "not_helpful",
    "verified_purchase",
    "city",
    "state",
    "variant",
    "found_via",
]


def get_state(html: str) -> Dict[str, Any]:
    """Return the ``window.__INITIAL_STATE__`` object, or ``{}`` if the page has none.

    ``raw_decode`` reads exactly one JSON value starting after the ``=`` and
    stops, so a ``};`` inside a product title cannot cut the object short.
    """
    match = _STATE_RE.search(html or "")
    if not match:
        return {}
    try:
        state, _ = json.JSONDecoder().raw_decode(html, match.end())
    except json.JSONDecodeError:
        return {}
    return state if isinstance(state, dict) else {}


def walk(node: Any, visit: Callable[[Dict[str, Any]], None]) -> None:
    """Call ``visit`` on every dict in a nested JSON structure."""
    if isinstance(node, dict):
        visit(node)
        for child in node.values():
            walk(child, visit)
    elif isinstance(node, list):
        for child in node:
            walk(child, visit)


def label(node: Any) -> str:
    """Text of a widget label node. Flipkart stores it as a string, a list or a number."""
    text = node.get("value", {}).get("text") if isinstance(node, dict) else None
    if isinstance(text, list):
        return " ".join(str(t) for t in text)
    return "" if text is None else str(text)


# --------------------------------------------------------------------------- search


def product_cards(state: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Yield every product card on a search page (list and grid layouts alike).

    The page is a grid of rows keyed by id ("10003" holds the results today).
    Every row is walked rather than hard-coding that key, and only
    ``PRODUCT_SUMMARY`` widgets are kept, which skips filters and pagination.
    """
    rows = state.get("pageDataV4", {}).get("page", {}).get("data", {})
    if not isinstance(rows, dict):
        return
    for slot_list in rows.values():
        for slot in slot_list or []:
            widget = (slot or {}).get("widget", {}) or {}
            if widget.get("type") == "PRODUCT_SUMMARY":
                yield from (widget.get("data", {}) or {}).get("products", []) or []


def parse_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Turn one ``PRODUCT_SUMMARY`` product into a flat row."""
    info = card.get("productInfo", {}) or {}
    value = info.get("value", {}) or {}
    # Unavailable products ship without a pricing object at all
    pricing = value.get("pricing", {}) or {}
    prices = pricing.get("prices", []) or []
    price = next((p.get("value") for p in prices if not p.get("strikeOff")), "")
    mrp = next((p.get("value") for p in prices if p.get("strikeOff")), "")
    rating = value.get("rating", {}) or {}
    tags = [t.get("type") for t in value.get("productCardTagDetails") or []]
    titles = value.get("titles", {}) or {}
    path = (info.get("action", {}) or {}).get("url", "")
    return {
        "product_id": value.get("id", ""),
        "listing_id": value.get("listingId", ""),
        "title": titles.get("title", ""),
        "subtitle": titles.get("subtitle", ""),
        "price": price,
        "mrp": mrp,
        "discount_pct": pricing.get("totalDiscount", ""),
        "rating": rating.get("average", ""),
        "ratings_count": rating.get("count", ""),
        "reviews_count": rating.get("reviewCount", ""),
        "availability": (value.get("availability", {}) or {}).get("displayState", ""),
        "f_assured": "F_ASSURED" in tags,
        # Sponsored placements carry an adInfo object
        "sponsored": bool(card.get("adInfo")),
        "key_specs": " | ".join(value.get("keySpecs") or []),
        "url": BASE_URL + path if path.startswith("/") else path,
    }


def parse_search(html_or_state: Any) -> List[Dict[str, Any]]:
    """Every product card on a search page, as rows (sponsored repeats included)."""
    state = get_state(html_or_state) if isinstance(html_or_state, str) else html_or_state
    return [parse_card(card) for card in product_cards(state)]


# --------------------------------------------------------------------------- product


def parse_product(html_or_state: Any) -> Dict[str, Any]:
    """Parse a product page into one row.

    Raises ``ValueError`` when the page has no product state, which usually
    means an empty state (default user agent) or a non-product page.
    """
    state = get_state(html_or_state) if isinstance(html_or_state, str) else html_or_state
    mws = state.get("multiWidgetState", {}) or {}
    page = mws.get("pageDataResponse", {}) or {}
    context = page.get("pageContext", {}) or {}
    if not context.get("productId"):
        raise ValueError("No product data found. Expected a Flipkart product page with its JSON state.")
    psi = ((context.get("fdpEventTracking", {}) or {}).get("events", {}) or {}).get("psi", {}) or {}

    specs: Dict[str, str] = {}
    seller: List[str] = []
    delivery: List[str] = []

    def pair(node: Dict[str, Any]) -> None:
        if "label_0" in node and "label_1" in node:
            name, val = label(node["label_0"]), label(node["label_1"])
            if name and val:
                specs.setdefault(name, val)

    def find_specs(node: Dict[str, Any]) -> None:
        # Spec rows only live under widget keys named rpd_specifications_*;
        # the same label_0/label_1 pattern also holds offers and delivery text.
        for key, child in node.items():
            if isinstance(key, str) and key.startswith("rpd_specifications"):
                walk(child, pair)

    def find_labels(node: Dict[str, Any]) -> None:
        texts = {k: label(v) for k, v in node.items() if isinstance(k, str) and k.startswith("label_")}
        # Electronics pages: "Delivery by" + date; fashion pages: "Delivery" + "by 29 Oct, Thu"
        if texts.get("label_0") == "Delivery by":
            delivery.append(texts.get("label_1", ""))
        if texts.get("label_2") == "Delivery" and texts.get("label_7", "").startswith("by "):
            delivery.append(texts["label_7"][3:])
        for text in texts.values():
            # Electronics pages say "Seller: X", fashion pages "Fulfilled by X"
            for prefix in ("Seller: ", "Fulfilled by "):
                if text.startswith(prefix):
                    seller.append(text[len(prefix):])

    for slot in (mws.get("widgetsData", {}) or {}).get("slots", []) or []:
        walk(slot, find_specs)
        walk(slot, find_labels)

    prices = psi.get("ppd", {}) or {}
    reviews = psi.get("pr", {}) or {}
    stars = {r.get("ratingValue"): r.get("ratingCount") for r in reviews.get("individualRatingsCount", []) or []}
    listing = psi.get("pls", {}) or {}
    policy = psi.get("pi", {}) or {}
    og_title = ((page.get("seoData", {}) or {}).get("seo", {}) or {}).get("ogTitle", "")
    row: Dict[str, Any] = {
        "product_id": context.get("productId", ""),
        "listing_id": context.get("listingId", ""),
        # ogTitle reads "name Rs.price Price in India - Buy..."
        "title": og_title.split(" Rs.")[0],
        "brand": psi.get("bd", ""),
        "price": prices.get("finalPrice", ""),
        "mrp": prices.get("mrp", ""),
        "rating": reviews.get("rating", ""),
        "ratings_count": reviews.get("ratingsCount", ""),
        "reviews_count": reviews.get("reviewsCount", ""),
    }
    for n in range(5, 0, -1):
        row[f"stars_{n}"] = stars.get(n, "")
    row.update(
        {
            "aspect_ratings": " | ".join(
                f"{a.get('parameter')}: {a.get('rating')}" for a in reviews.get("parameterRating", []) or []
            ),
            "seller": seller[0] if seller else "",
            "seller_id": listing.get("sellerId", ""),
            "availability": listing.get("availabilityStatus", ""),
            "cod": policy.get("isCODAvailable", ""),
            "return_policy": policy.get("returnPolicy", ""),
            "delivery_by": delivery[0] if delivery else "",
            "offer_count": (psi.get("os", {}) or {}).get("offerCount", ""),
            "spec_count": len(specs),
            "specs": " | ".join(f"{k}: {v}" for k, v in specs.items()),
            "url": "",
        }
    )
    return row


# --------------------------------------------------------------------------- reviews


def review_values(state: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Yield the raw review objects from a review page's ``REVIEWS`` widgets."""
    slots = ((state.get("multiWidgetState", {}) or {}).get("widgetsData", {}) or {}).get("slots", []) or []
    for slot in slots:
        widget = ((slot or {}).get("slotData", {}) or {}).get("widget", {}) or {}
        if widget.get("type") == "REVIEWS":
            for component in (widget.get("data", {}) or {}).get("renderableComponents", []) or []:
                yield (component or {}).get("value", {}) or {}


def parse_review(r: Dict[str, Any], found_via: str = "") -> Dict[str, Any]:
    """One review as a flat row. The reviewer's display name is left out on purpose."""
    location = r.get("location") or {}
    return {
        "review_id": r.get("id", ""),
        "rating": r.get("rating", ""),
        "title": r.get("title", ""),
        "text": (r.get("text") or "").replace("\n", " "),
        "created": r.get("created", ""),
        "helpful": ((r.get("upvote") or {}).get("value", {}) or {}).get("count", ""),
        "not_helpful": ((r.get("downvote") or {}).get("value", {}) or {}).get("count", ""),
        "verified_purchase": r.get("certifiedBuyer", ""),
        "city": location.get("city", ""),
        "state": location.get("state", ""),
        "variant": " | ".join(f"{a.get('name')}: {a.get('value')}" for a in r.get("productAttributeList") or []),
        "found_via": found_via,
    }


def parse_reviews(html_or_state: Any, found_via: str = "") -> List[Dict[str, Any]]:
    """Every review on one review page (Flipkart serves 10 per page)."""
    state = get_state(html_or_state) if isinstance(html_or_state, str) else html_or_state
    return [parse_review(r, found_via) for r in review_values(state)]


def flatten(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Copy rows so every value is CSV-safe (None becomes an empty string)."""
    return [{k: ("" if v is None else v) for k, v in row.items()} for row in rows]

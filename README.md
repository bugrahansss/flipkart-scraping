# flipkart-scraping

[![PyPI](https://img.shields.io/pypi/v/flipkart-scraping)](https://pypi.org/project/flipkart-scraping/)
[![Python](https://img.shields.io/pypi/pyversions/flipkart-scraping)](https://pypi.org/project/flipkart-scraping/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Python scraper for [Flipkart](https://www.flipkart.com) search results, product details and product reviews. It reads the JSON state Flipkart embeds in every page instead of CSS classes, so the same code works on the list layout (laptops, phones) and the grid layout (shoes, fashion), and survives frontend rebuilds that rename classes.

```bash
pip install flipkart-scraping
```

## Why most Flipkart scrapers break

Flipkart rarely blocks a request. It breaks scrapers quietly:

| Problem | What happens |
|---|---|
| **Empty state for non-browsers** | `python-requests` and `curl` user agents get a 200 page with `window.__INITIAL_STATE__ = {}`. The data object is missing; only the HTML is left. |
| **Hashed class names** | Classes like `RG5Slk` change with each build. The old `._30jeq3` price and `._4rR01T` name selectors match nothing today. |
| **Two card layouts** | Search results come as 24 list cards or 40 grid cards, each with its own classes. A selector that matches 24 of 24 laptop cards matches 0 of 40 shoe cards. |
| **Page ceilings** | Search stops serving products around page 25 (41 on "laptop"); reviews stop after 20 pages per sort order. |

This package fetches each page through the [Scrape.do](https://scrape.do/?utm_source=github&utm_medium=readme&utm_campaign=flipkart-scraping) API with `geoCode=in` (an Indian exit IP, Flipkart's only market) and reads the full JSON state: 1 credit per page, no browser. `render=true` is not used on purpose: the rendered DOM no longer contains the state script. You need a Scrape.do API token; the free plan includes 1,000 credits a month.

## Quick start

```python
from flipkart_scraping import FlipkartScraper

scraper = FlipkartScraper(token="YOUR_SCRAPEDO_TOKEN")  # or set SCRAPEDO_TOKEN

products = scraper.search("laptop", max_pages=3)          # one row per unique product
details = scraper.get_product(products[0]["url"])          # seller, full specs, star breakdown
reviews = scraper.get_reviews(products[0]["url"])          # up to 200 per sort order, 4 orders

print(products[0]["title"], products[0]["price"], products[0]["mrp"])
print(details["seller"], details["spec_count"], details["delivery_by"])
print(len(reviews), reviews[0]["rating"], reviews[0]["title"])
```

### Command line

```bash
export SCRAPEDO_TOKEN=your_token

# search results, 3 pages, CSV
flipkart-scraping search "laptop" --pages 3 --format csv -o flipkart-search.csv

# one price band, to get past the page ceiling
flipkart-scraping search "laptop" --pages 25 --min-price 50000 --max-price 70000 -f csv -o band.csv

# product details for every URL in a file
flipkart-scraping product --input urls.txt --format csv -o flipkart-products.csv

# reviews, all four sort orders, deduplicated
flipkart-scraping reviews "https://www.flipkart.com/<product>/p/<itm-id>?pid=<pid>" -f csv -o flipkart-reviews.csv
```

### Output

Search row, from the fictional test page in [`tests/fixtures`](tests/fixtures/search_laptop.html):

```json
{
  "product_id": "COMEXAMPLE0001",
  "listing_id": "LSTCOMEXAMPLE0001AAA",
  "title": "Nimbus Book 14 Example Core 7 - (16 GB/512 GB SSD) }; edition",
  "subtitle": "Grey, 1.6 kg",
  "price": 79990,
  "mrp": 123490,
  "discount_pct": 35,
  "rating": 4.4,
  "ratings_count": 6128,
  "reviews_count": 557,
  "availability": "IN_STOCK",
  "f_assured": true,
  "sponsored": true,
  "key_specs": "Example Core 7 Processor | 16 GB RAM | 512 GB SSD",
  "url": "https://www.flipkart.com/example-comexample0001/p/itmexample0001?pid=COMEXAMPLE0001&lid=LSTCOMEXAMPLE0001AAA&marketplace=FLIPKART&q=laptop"
}
```

## Fields

| Scraper | Fields |
|---|---|
| `search` | `product_id`, `listing_id`, `title`, `subtitle`, `price`, `mrp`, `discount_pct`, `rating`, `ratings_count`, `reviews_count`, `availability`, `f_assured`, `sponsored`, `key_specs`, `url` |
| `get_product` | `product_id`, `listing_id`, `title`, `brand`, `price`, `mrp`, `rating`, `ratings_count`, `reviews_count`, `stars_5` to `stars_1`, `aspect_ratings`, `seller`, `seller_id`, `availability`, `cod`, `return_policy`, `delivery_by`, `offer_count`, `spec_count`, `specs`, `url` |
| `get_reviews` | `review_id`, `rating`, `title`, `text`, `created`, `helpful`, `not_helpful`, `verified_purchase`, `city`, `state`, `variant`, `found_via` |

List values (key specs, specs, aspect ratings, variant) are joined with ` | `, so every row fits in one CSV line. MRP is India's maximum retail price; `f_assured` marks listings Flipkart stores and ships itself.

## How the parser works

Every Flipkart page assigns one JSON object to `window.__INITIAL_STATE__`. The parser finds that assignment and reads exactly one JSON value with `json.JSONDecoder().raw_decode`, so a `};` inside a product title cannot cut it short.

- **Search pages** keep products as `PRODUCT_SUMMARY` widgets under `pageDataV4.page.data`. Every row is walked and only that widget type is kept, which skips filters and pagination. Prices are picked by the `strikeOff` flag (MRP) rather than by position, and unavailable products, which ship without a pricing object, get a blank price instead of a crash.
- **Product pages** use `multiWidgetState`. Price, ratings, star breakdown, aspect ratings, seller id, COD and return policy come from `pageContext.fdpEventTracking.events.psi`. Specs are the `label_0`/`label_1` pairs under widget keys starting with `rpd_specifications`. The seller name and delivery date are label text, worded differently on electronics pages (`Seller: X`, `Delivery by`) and fashion pages (`Fulfilled by X`, `Delivery` + `by 29 Oct, Thu`); both are handled.
- **Review pages** hold each review as a value inside a `REVIEWS` widget, with the full text, vote counts, location and purchased variant.

You can also parse HTML you already have:

```python
from flipkart_scraping import parse_search, parse_product, parse_reviews

rows = parse_search(html)
```

## Limits

- **Page ceilings.** Search stops after about 25 pages; split busy searches into price bands with `min_price`/`max_price`, and halve any band that still reaches the ceiling. Reviews stop at 20 pages of 10 per sort order; `get_reviews` runs all four orders and removes duplicates, which reached 77% of one product's reviews in testing.
- **Seller offers.** The `lid` parameter in a product URL decides which seller's offer the page shows. `get_product` keeps it, so prices match the search card. Drop it to get Flipkart's default offer.
- **Delivery date** is Flipkart's estimate for its default location, not for a specific PIN code.
- **Undocumented state.** The JSON shape can change without notice. The scrapers stop on an empty page and leave a blank cell for a missing key rather than writing wrong data; re-run them before trusting a new month's CSV.
- **Errors.** Non-200 responses raise `ScrapeError` with the status code. Server errors and 429s are retried twice; client errors are not.

## Responsible use

Review rows leave out the reviewer's display name on purpose: a name next to a city is personal data under India's Digital Personal Data Protection Act, and it adds nothing to rating or sentiment analysis. Follow Flipkart's terms and the laws that apply to you, and keep request rates reasonable. This is not legal advice.

## Development

```bash
git clone https://github.com/bugrahansss/flipkart-scraping
cd flipkart-scraping
pip install -e .
python -m unittest discover -s tests -v
```

The tests run offline against fictional fixture pages.

## License

MIT

---

Source: [Scraping Flipkart in 2026: Extract Search Results, Product Details, and Reviews with Python](https://scrape.do/?utm_source=github&utm_medium=readme&utm_campaign=flipkart-scraping)

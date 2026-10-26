"""Collect every laptop in several price bands to get past Flipkart's page ceiling.

Usage:
    export SCRAPEDO_TOKEN=your_token
    python price_bands.py laptops.csv

Flipkart stops serving search products after about page 25. Splitting a search
into price bands gives each band its own ceiling; if a band still reaches page
25, halve it.
"""

import csv
import sys

from flipkart_scraping import SEARCH_FIELDS, FlipkartScraper

BANDS = [(0, 30000), (30000, 50000), (50000, 70000), (70000, 100000), (100000, None)]


def main(out_file: str, query: str = "laptop") -> None:
    scraper = FlipkartScraper()  # reads SCRAPEDO_TOKEN
    rows = {}
    for low, high in BANDS:
        band = scraper.search(query, max_pages=25, min_price=low, max_price=high)
        for row in band:
            rows.setdefault(row["product_id"], row)
        print(f"Rs {low} to {high or 'max'}: {len(band)} products, {len(rows)} unique so far")

    with open(out_file, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SEARCH_FIELDS)
        writer.writeheader()
        writer.writerows(rows.values())
    print(f"Saved {len(rows)} products to {out_file}")


if __name__ == "__main__":
    main(*sys.argv[1:3])

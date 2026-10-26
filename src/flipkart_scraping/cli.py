"""Command line entry point: ``flipkart-scraping search|product|reviews ...``."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, Dict, List, Optional

from . import __version__
from .client import REVIEW_PAGE_CEILING, REVIEW_SORTS, TOKEN_ENV, FlipkartScraper, ScrapeError
from .parser import PRODUCT_FIELDS, REVIEW_FIELDS, SEARCH_FIELDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flipkart-scraping",
        description="Scrape Flipkart search results, product details and reviews into JSON or CSV.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-t", "--token", help=f"Scrape.do API token (default: ${TOKEN_ENV})")
    common.add_argument("-f", "--format", choices=("json", "csv"), default="json", help="Output format (default: json)")
    common.add_argument("-o", "--output", help="Write to this file instead of stdout")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", parents=[common], help="Search results, one row per unique product")
    s.add_argument("query", help='Search term, for example "laptop"')
    s.add_argument("--pages", type=int, default=3, help="Result pages to read (Flipkart stops near 25)")
    s.add_argument("--min-price", type=int, help="Lower end of a price band, in rupees")
    s.add_argument("--max-price", type=int, help="Upper end of a price band, in rupees")
    s.add_argument("--limit", type=int, help="Stop after this many products")

    p = sub.add_parser("product", parents=[common], help="Product details for one or more product URLs")
    p.add_argument("urls", nargs="*", help="Product URLs (keep pid and lid)")
    p.add_argument("-i", "--input", help="Text file with one product URL per line")

    r = sub.add_parser("reviews", parents=[common], help="Reviews for one product URL")
    r.add_argument("url", help="Product URL or reviews URL")
    r.add_argument("--sorts", default=",".join(REVIEW_SORTS), help="Comma-separated sort orders (default: all four)")
    r.add_argument("--pages", type=int, default=REVIEW_PAGE_CEILING, help="Pages per sort order (max 20 served)")
    r.add_argument("--limit", type=int, help="Stop after this many reviews")
    return parser


def _write(rows: List[Dict[str, Any]], fields: List[str], fmt: str, stream) -> None:
    if fmt == "csv":
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        json.dump(rows, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        scraper = FlipkartScraper(token=args.token)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    failures = 0
    try:
        if args.command == "search":
            rows = scraper.search(args.query, args.pages, args.min_price, args.max_price, args.limit)
            fields = SEARCH_FIELDS
        elif args.command == "reviews":
            sorts = [s.strip().upper() for s in args.sorts.split(",") if s.strip()]
            rows = scraper.get_reviews(args.url, sorts, args.pages, args.limit)
            fields = REVIEW_FIELDS
        else:
            urls = list(args.urls)
            if args.input:
                with open(args.input, encoding="utf-8") as handle:
                    urls.extend(line.strip() for line in handle if line.strip() and not line.startswith("#"))
            if not urls:
                print("No URLs given. Pass product URLs or --input FILE.", file=sys.stderr)
                return 2
            rows, fields = [], PRODUCT_FIELDS
            for url in urls:
                try:
                    rows.append(scraper.get_product(url))
                    print(f"ok    {url}", file=sys.stderr)
                except (ScrapeError, ValueError) as exc:
                    failures += 1
                    print(f"fail  {url}: {exc}", file=sys.stderr)
    except (ScrapeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="" if args.format == "csv" else None) as handle:
            _write(rows, fields, args.format, handle)
        print(f"Saved {len(rows)} row(s) to {args.output}", file=sys.stderr)
    else:
        _write(rows, fields, args.format, sys.stdout)
    return 1 if failures and not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())

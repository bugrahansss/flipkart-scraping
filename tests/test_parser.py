import csv
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from flipkart_scraping import (
    PRODUCT_FIELDS,
    SEARCH_FIELDS,
    FlipkartScraper,
    ScrapeError,
    clean_product_url,
    get_state,
    parse_product,
    parse_reviews,
    parse_search,
    reviews_url,
    search_url,
)
from flipkart_scraping import cli

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


PRODUCT_URL = "https://www.flipkart.com/example-comexample0001/p/itmexample0001?pid=COMEXAMPLE0001&lid=LSTCOMEXAMPLE0001AAA&marketplace=FLIPKART&q=laptop"


class StateTest(unittest.TestCase):
    def test_reads_state_with_brace_in_title(self):
        state = get_state(fixture("search_laptop.html"))
        self.assertIn("pageDataV4", state)

    def test_default_user_agent_page_has_empty_state(self):
        self.assertEqual(get_state(fixture("default_user_agent.html")), {})
        self.assertEqual(parse_search(fixture("default_user_agent.html")), [])

    def test_no_state_at_all(self):
        self.assertEqual(get_state("<html><body>nothing</body></html>"), {})


class SearchTest(unittest.TestCase):
    def test_cards(self):
        rows = parse_search(fixture("search_laptop.html"))
        self.assertEqual(len(rows), 4)  # sponsored repeat still present at parse level
        first = rows[0]
        self.assertEqual(list(first), SEARCH_FIELDS)
        self.assertEqual(first["product_id"], "COMEXAMPLE0001")
        self.assertEqual((first["price"], first["mrp"], first["discount_pct"]), (79990, 123490, 35))
        self.assertEqual((first["rating"], first["ratings_count"], first["reviews_count"]), (4.4, 6128, 557))
        self.assertTrue(first["sponsored"])
        self.assertTrue(first["f_assured"])
        self.assertTrue(first["url"].startswith("https://www.flipkart.com/"))
        self.assertFalse(rows[1]["f_assured"])

    def test_unavailable_product_has_blank_price(self):
        row = parse_search(fixture("search_laptop.html"))[2]
        self.assertEqual(row["availability"], "NO_AVAILABLE_LISTING")
        self.assertEqual((row["price"], row["mrp"]), ("", ""))

    def test_empty_results_page(self):
        self.assertEqual(parse_search(fixture("search_empty.html")), [])


class ProductTest(unittest.TestCase):
    def test_laptop(self):
        p = parse_product(fixture("product_laptop.html"))
        self.assertEqual(list(p), PRODUCT_FIELDS)
        self.assertEqual(p["title"], "Nimbus Book 14 Example Core 7 - (16 GB/512 GB SSD)")
        self.assertEqual((p["price"], p["mrp"], p["brand"]), (79990, 123490, "Nimbus"))
        self.assertEqual((p["stars_5"], p["stars_1"]), (4093, 344))
        self.assertEqual(p["aspect_ratings"], "Design: 4.6 | Sound Quality: 3.9")
        self.assertEqual((p["seller"], p["delivery_by"]), ("ExampleRetail", "Monday, 2 Nov"))
        self.assertEqual((p["cod"], p["offer_count"]), (True, 37))
        # Offers use label_0/label_1 too but sit outside rpd_specifications; duplicates keep the first value
        self.assertEqual(p["spec_count"], 5)
        self.assertIn("RAM: 16 GB", p["specs"])
        self.assertIn("Weight: 1.6", p["specs"])
        self.assertNotIn("Bank Offer", p["specs"])

    def test_fashion_wording(self):
        p = parse_product(fixture("product_shoes.html"))
        self.assertEqual((p["seller"], p["delivery_by"]), ("ExampleShoes", "29 Oct, Thu"))

    def test_not_a_product(self):
        with self.assertRaises(ValueError):
            parse_product(fixture("search_laptop.html"))


class ReviewsTest(unittest.TestCase):
    def test_reviews(self):
        rows = parse_reviews(fixture("reviews_page.html"), found_via="MOST_HELPFUL")
        self.assertEqual(len(rows), 2)
        r = rows[0]
        self.assertEqual((r["rating"], r["helpful"], r["not_helpful"]), (5, 437, 105))
        self.assertEqual(r["text"], "Fast and light. Battery lasts all day.")
        self.assertEqual((r["city"], r["state"]), ("Example City", "Example State"))
        self.assertEqual(r["variant"], "Color: Gray | System Memory: 16 GB")
        self.assertNotIn("author", r)


class UrlTest(unittest.TestCase):
    def test_search_url_with_price_band(self):
        url = search_url("gaming laptop", page=2, min_price=50000, max_price=70000)
        self.assertEqual(
            url,
            "https://www.flipkart.com/search?q=gaming+laptop&page=2"
            "&p%5B%5D=facets.price_range.from%3D50000&p%5B%5D=facets.price_range.to%3D70000",
        )

    def test_clean_and_reviews_url(self):
        clean = clean_product_url(PRODUCT_URL)
        self.assertTrue(clean.endswith("?pid=COMEXAMPLE0001&lid=LSTCOMEXAMPLE0001AAA"))
        self.assertEqual(
            reviews_url(PRODUCT_URL),
            "https://www.flipkart.com/example-comexample0001/product-reviews/itmexample0001?pid=COMEXAMPLE0001",
        )
        with self.assertRaises(ValueError):
            reviews_url("https://www.flipkart.com/search?q=laptop")


def _response(status, text=""):
    r = mock.Mock()
    r.status_code, r.text = status, text
    return r


class ClientTest(unittest.TestCase):
    def test_requires_token(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                FlipkartScraper()

    def test_request_parameters(self):
        session = mock.Mock()
        session.get.return_value = _response(200, fixture("product_laptop.html"))
        row = FlipkartScraper(token="T", session=session).get_product(PRODUCT_URL)
        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["geoCode"], "in")
        self.assertNotIn("render", kwargs["params"])
        self.assertEqual(kwargs["params"]["url"], clean_product_url(PRODUCT_URL))
        self.assertEqual(row["url"], clean_product_url(PRODUCT_URL))

    def test_search_dedupes_and_stops_on_empty_page(self):
        session = mock.Mock()
        session.get.side_effect = [
            _response(200, fixture("search_laptop.html")),
            _response(200, fixture("search_laptop.html")),
            _response(200, fixture("search_empty.html")),
        ]
        rows = FlipkartScraper(token="T", session=session).search("laptop", max_pages=10)
        self.assertEqual([r["product_id"] for r in rows], ["COMEXAMPLE0001", "COMEXAMPLE0002", "COMEXAMPLE0003"])
        self.assertEqual(session.get.call_count, 3)

    def test_reviews_across_sort_orders(self):
        session = mock.Mock()
        empty = '<script>window.__INITIAL_STATE__ = {"multiWidgetState": {"widgetsData": {"slots": []}}};</script>'
        session.get.side_effect = [
            _response(200, fixture("reviews_page.html")), _response(200, empty),
            _response(200, fixture("reviews_page.html")), _response(200, empty),
        ]
        rows = FlipkartScraper(token="T", session=session).get_reviews(PRODUCT_URL, sorts=["MOST_HELPFUL", "MOST_RECENT"])
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["found_via"] for r in rows}, {"MOST_HELPFUL"})
        first_target = session.get.call_args_list[0][1]["params"]["url"]
        self.assertIn("/product-reviews/", first_target)
        self.assertTrue(first_target.endswith("sortOrder=MOST_HELPFUL&page=1"))

    def test_client_error_is_not_retried(self):
        session = mock.Mock()
        session.get.return_value = _response(401)
        with self.assertRaises(ScrapeError) as ctx:
            FlipkartScraper(token="T", session=session, retries=3).fetch(PRODUCT_URL)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(session.get.call_count, 1)

    @mock.patch("flipkart_scraping.client.time.sleep")
    def test_server_error_is_retried(self, _sleep):
        session = mock.Mock()
        session.get.side_effect = [_response(502), _response(200, "ok")]
        self.assertEqual(FlipkartScraper(token="T", session=session, retries=2).fetch(PRODUCT_URL), "ok")
        self.assertEqual(session.get.call_count, 2)


class CliTest(unittest.TestCase):
    def _run(self, argv, html):
        out = io.StringIO()
        with mock.patch("flipkart_scraping.client.FlipkartScraper.fetch", return_value=html), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", io.StringIO()):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_product_json(self):
        code, out = self._run(["product", PRODUCT_URL, "--token", "T"], fixture("product_laptop.html"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["seller"], "ExampleRetail")

    def test_search_csv(self):
        code, out = self._run(["search", "laptop", "--pages", "1", "--token", "T", "--format", "csv"], fixture("search_laptop.html"))
        self.assertEqual(code, 0)
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["price"], "79990")


if __name__ == "__main__":
    unittest.main()

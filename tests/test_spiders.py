from decimal import Decimal

from scrapy import Request

from crawlers.items import BookItem, PriceItem, QuoteItem
from crawlers.spiders.books import BooksSpider
from crawlers.spiders.iso_prices import IsoPricesSpider
from crawlers.spiders.quotes_api import QuotesApiSpider, page_url

BOOK_URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


class TestBooksSpider:
    def test_listing_yields_detail_requests_and_next_page(self, html_response):
        spider = BooksSpider()
        response = html_response("books_listing.html", "https://books.toscrape.com/")
        results = list(spider.parse(response))

        assert all(isinstance(r, Request) for r in results)
        detail = [r for r in results if r.callback == spider.parse_book]
        assert len(detail) == 20
        assert detail[0].url.startswith("https://books.toscrape.com/catalogue/")
        nxt = [r for r in results if r.callback == spider.parse]
        assert [r.url for r in nxt] == ["https://books.toscrape.com/catalogue/page-2.html"]
        # every detail request carries its errback and our own data in cb_kwargs
        assert all(r.errback is not None for r in results)
        assert detail[0].cb_kwargs == {"list_url": "https://books.toscrape.com/"}

    def test_detail_page_is_parsed_and_typed(self, html_response):
        spider = BooksSpider()
        response = html_response("book_detail.html", BOOK_URL)
        (item,) = spider.parse_book(response, list_url="https://books.toscrape.com/")

        assert isinstance(item, BookItem)
        assert item.title == "A Light in the Attic"
        assert item.price_gbp == Decimal("51.77")
        assert item.rating == 3
        assert item.availability == 22
        assert item.upc == "a897fe39b1053632"
        assert item.category == "Poetry"
        assert item.description.startswith("It's hard to imagine a world without")
        assert item.url == BOOK_URL


class TestQuotesCrawlRules:
    def test_rule_follows_main_pagination_but_not_tag_pages(self):
        # Regression for a real bug: an unanchored regex also matched /tag/<x>/page/<n>/ and the
        # spider crawled every tag listing, producing 3x duplicate items.
        from scrapy.http import HtmlResponse

        from crawlers.spiders.quotes_crawl import QuotesCrawlSpider

        body = b"""<html><body>
          <a href="/page/2/">next</a>
          <a href="/page/10/">ten</a>
          <a href="/tag/love/page/2/">tag page</a>
          <a href="/tag/love/">tag</a>
          <a href="/author/Albert-Einstein">author</a>
        </body></html>"""
        response = HtmlResponse("https://quotes.toscrape.com/", body=body, encoding="utf-8")
        extractor = QuotesCrawlSpider.rules[0].link_extractor
        urls = sorted(link.url for link in extractor.extract_links(response))
        assert urls == [
            "https://quotes.toscrape.com/page/10/",
            "https://quotes.toscrape.com/page/2/",
        ]


class TestQuotesApiSpider:
    def test_parses_json_and_follows_pagination(self):
        import json
        from pathlib import Path

        from scrapy.http import TextResponse

        body = (Path(__file__).parent / "fixtures" / "quotes_api_page1.json").read_bytes()
        response = TextResponse(url=page_url(1), body=body, encoding="utf-8")
        results = list(QuotesApiSpider().parse_page(response))

        items = [r for r in results if isinstance(r, QuoteItem)]
        requests = [r for r in results if isinstance(r, Request)]
        assert len(items) == len(json.loads(body)["quotes"]) > 0
        assert items[0].author and items[0].text
        assert [r.url for r in requests] == [page_url(2)]


class TestIsoPricesSpider:
    def make(self, make_crawler, **kw):
        kw.setdefault("start_date", "2026-06-15")
        return make_crawler({"ISO_BASE_URL": "http://127.0.0.1:8765"}, IsoPricesSpider, **kw)

    def test_requires_start_date(self, make_crawler):
        import pytest

        with pytest.raises(ValueError, match="start_date is required"):
            make_crawler({}, IsoPricesSpider)

    def test_normal_day_parses_every_row_including_bad_prices(self, make_crawler, csv_response):
        crawler, spider = self.make(make_crawler)
        items = list(spider.parse_day(csv_response("2026-06-15"), spider.start_date))
        assert len(items) == 48 and all(isinstance(i, PriceItem) for i in items)
        assert sum(i.price_usd_mwh is None for i in items) == 1  # "N/A"; validation will drop it
        assert any(i.price_usd_mwh == Decimal("-8.40") for i in items)  # negative is legal
        assert crawler.stats.get_value("iso/incomplete_day") is None

    def test_fall_back_day_has_unique_utc_keys(self, make_crawler, csv_response):
        crawler, spider = self.make(make_crawler, start_date="2026-11-01")
        items = list(spider.parse_day(csv_response("2026-11-01"), spider.start_date))
        assert len(items) == 50  # 25 hours x 2 nodes
        assert len({(i.node, i.interval_start_utc) for i in items}) == 50  # nothing collides
        assert crawler.stats.get_value("iso/incomplete_day") is None

    def test_spring_forward_day_has_23_hours(self, make_crawler, csv_response):
        crawler, spider = self.make(make_crawler, start_date="2026-03-08")
        items = list(spider.parse_day(csv_response("2026-03-08"), spider.start_date))
        assert len(items) == 46
        assert crawler.stats.get_value("iso/bad_interval") is None
        assert crawler.stats.get_value("iso/incomplete_day") is None

    def test_missing_hour_is_detected_not_filled(self, make_crawler, csv_response):
        crawler, spider = self.make(make_crawler, start_date="2026-06-16")
        items = list(spider.parse_day(csv_response("2026-06-16"), spider.start_date))
        assert len(items) == 47
        assert crawler.stats.get_value("iso/incomplete_day") == 1

    def test_nonexistent_interval_is_counted_and_skipped(self, make_crawler):
        from scrapy.http import TextResponse

        body = b"date,hour_ending,dst_flag,node,lmp_usd_mwh\n2026-03-08,3,0,HUB_A,40.00\n"
        crawler, spider = self.make(make_crawler, start_date="2026-03-08")
        response = TextResponse("http://x/p.csv", body=body, encoding="utf-8")
        assert list(spider.parse_day(response, spider.start_date)) == []
        assert crawler.stats.get_value("iso/bad_interval") == 1

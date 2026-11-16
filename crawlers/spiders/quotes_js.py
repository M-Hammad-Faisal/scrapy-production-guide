"""JavaScript rendering with scrapy-playwright: the LAST resort.

https://quotes.toscrape.com/js/ builds its content in the browser. Compare this spider with
``quotes_api``: same data, but this one needs a real browser and is far slower and heavier.

Install the optional dependency and browser first:
    uv pip install -e ".[browser]" && playwright install chromium
    scrapy crawl quotes_js -s MIN_ITEMS=1

Gotchas shown in the settings below:
* the asyncio reactor is required,
* keep concurrency LOW (every request is a browser page),
* only requests with meta={"playwright": True} use the browser; the rest stay plain HTTP,
* close pages you open yourself (not needed here because we do not request the page object).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

from scrapy import Request
from scrapy.http import TextResponse

from crawlers.items import QuoteItem
from crawlers.spiders.base import BaseSpider


class QuotesJsSpider(BaseSpider):
    name = "quotes_js"
    allowed_domains = ["quotes.toscrape.com"]

    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
    }

    async def start(self) -> AsyncIterator[Any]:
        yield self._page_request("https://quotes.toscrape.com/js/")

    def _page_request(self, url: str) -> Request:
        return Request(
            url,
            callback=self.parse_page,
            errback=self.errback_log,
            meta={
                "playwright": True,
                # Wait for the element we need instead of sleeping for a fixed time.
                "playwright_page_methods": [
                    {"method": "wait_for_selector", "args": ["div.quote"]},
                ],
            },
        )

    def parse_page(self, response: TextResponse) -> Iterator[Any]:
        for quote in response.css("div.quote"):
            yield QuoteItem(
                text=quote.css("span.text::text").get(),
                author=quote.css("small.author::text").get(),
                tags=quote.css("div.tags a.tag::text").getall(),
                source_url=response.url,
            )
        next_href = response.css("li.next a::attr(href)").get()
        if next_href:
            yield self._page_request(response.urljoin(next_href))

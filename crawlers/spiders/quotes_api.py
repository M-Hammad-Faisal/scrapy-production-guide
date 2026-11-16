"""Find the real API first.

https://quotes.toscrape.com/scroll loads quotes with JavaScript, but the browser gets them from a
plain JSON endpoint. Calling that endpoint directly means: no browser, no HTML parsing, far faster
and far less fragile. This is the single most valuable habit in scraping:

  1. Open DevTools -> Network -> filter XHR/Fetch.
  2. Reload and scroll. Find the request that returns the data.
  3. Replicate it in a spider (copy as cURL helps) and parse ``response.json()``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from urllib.parse import urlencode

from scrapy import Request
from scrapy.http import TextResponse

from crawlers.items import QuoteItem
from crawlers.spiders.base import BaseSpider

API_URL = "https://quotes.toscrape.com/api/quotes"


def page_url(page: int) -> str:
    # urlencode builds the query string safely; never paste user input into a URL by hand.
    return f"{API_URL}?{urlencode({'page': page})}"


class QuotesApiSpider(BaseSpider):
    name = "quotes_api"
    allowed_domains = ["quotes.toscrape.com"]

    async def start(self) -> AsyncIterator[Any]:
        # `start()` replaces start_requests() in modern Scrapy. Use it when start requests are
        # computed (here, a page number; in iso_prices, a date range).
        yield Request(page_url(1), callback=self.parse_page, errback=self.errback_log)

    def parse_page(self, response: TextResponse) -> Iterator[Any]:
        data = response.json()
        for q in data["quotes"]:
            yield QuoteItem(
                text=q["text"],
                author=q["author"]["name"],
                tags=q["tags"],
                source_url=response.url,
            )
        if data.get("has_next"):
            yield Request(
                page_url(data["page"] + 1),
                callback=self.parse_page,
                errback=self.errback_log,
            )

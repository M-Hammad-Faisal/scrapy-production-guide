"""CrawlSpider: declare link-following rules instead of writing pagination code.

Use CrawlSpider when links follow a pattern and there is little per-page logic. Use a plain
Spider when you need control (like books.py). Gotcha: a CrawlSpider callback must NOT be named
``parse``; CrawlSpider uses ``parse`` itself and overriding it silently breaks the rules.
"""

from __future__ import annotations

from collections.abc import Iterator

from scrapy.http import Response
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from crawlers.items import QuoteItem


class QuotesCrawlSpider(CrawlSpider):
    name = "quotes_crawl"
    allowed_domains = ["quotes.toscrape.com"]
    start_urls = ["https://quotes.toscrape.com/"]

    rules = (
        # Follow ONLY the main pagination: https://quotes.toscrape.com/page/2/
        #
        # Real bug found while building this repo: the first version used allow=r"/page/\d+/".
        # LinkExtractor `allow` is a regex SEARCH, not a full match, so it also matched
        # /tag/love/page/2/ and the spider crawled every tag listing (342 items for 100 quotes).
        # Anchor the pattern to the whole URL.
        Rule(
            LinkExtractor(allow=r"^https://quotes\.toscrape\.com/page/\d+/$"),
            callback="parse_page",
            follow=True,
        ),
    )

    def parse_start_url(self, response: Response) -> Iterator[QuoteItem]:
        # Rules only apply to LINKS FOUND on pages. The start page itself needs this hook.
        yield from self.parse_page(response)

    def parse_page(self, response: Response) -> Iterator[QuoteItem]:
        for quote in response.css("div.quote"):
            yield QuoteItem(
                text=quote.css("span.text::text").get(),
                author=quote.css("small.author::text").get(),
                tags=quote.css("div.tags a.tag::text").getall(),
                source_url=response.url,
            )

"""Classic listing -> detail spider (static HTML).

Teaches: start_urls, response.follow, pagination, cb_kwargs, ItemLoader, errback, contracts.
Practice site: https://books.toscrape.com (built for scraping practice).
"""

from __future__ import annotations

from collections.abc import Iterator

from scrapy import Request
from scrapy.http import Response

from crawlers.items import BookItem
from crawlers.loaders import BookLoader
from crawlers.spiders.base import BaseSpider


class BooksSpider(BaseSpider):
    name = "books"
    allowed_domains = ["books.toscrape.com"]
    start_urls = ["https://books.toscrape.com/"]

    def parse(self, response: Response) -> Iterator[Request]:
        """Listing page: follow every book, then the next page.

        @url https://books.toscrape.com/
        @returns requests 20 21
        """
        # css(...).getall() returns hrefs; response.follow resolves relative URLs for us.
        for href in response.css("article.product_pod h3 a::attr(href)").getall():
            yield response.follow(
                href,
                callback=self.parse_book,
                errback=self.errback_log,
                cb_kwargs={"list_url": response.url},  # cb_kwargs, not meta, for your own data
            )

        # Pagination: follow "next" if it exists. No next link means the last page.
        next_href = response.css("li.next a::attr(href)").get()
        if next_href:
            yield response.follow(next_href, callback=self.parse, errback=self.errback_log)

    def parse_book(self, response: Response, list_url: str | None = None) -> Iterator[BookItem]:
        """Detail page -> one BookItem.

        Gotcha: `scrapy check` runs contracts by calling the callback with ONLY the response, so
        any cb_kwargs argument needs a default value or the contract crashes.

        @url https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
        @returns items 1 1
        @scrapes title price_gbp rating upc
        """
        loader = BookLoader(item=BookItem(), response=response)
        loader.add_value("url", response.url)
        loader.add_css("title", "div.product_main h1::text")
        loader.add_css("price_gbp", "div.product_main p.price_color::text")
        loader.add_css("rating", "div.product_main p.star-rating::attr(class)")
        # xpath string() joins text split across tags; ::text would return only direct text nodes.
        loader.add_xpath("availability", "string(//div[contains(@class,'product_main')]//p[2])")
        loader.add_xpath("upc", "//th[normalize-space()='UPC']/following-sibling::td/text()")
        loader.add_css("category", "ul.breadcrumb li:nth-child(3) a::text")
        loader.add_xpath(
            "description", "//div[@id='product_description']/following-sibling::p/text()"
        )
        yield loader.load_item()

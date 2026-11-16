from pathlib import Path

import pytest
from scrapy import Spider
from scrapy.http import HtmlResponse, TextResponse
from scrapy.utils.test import get_crawler

FIXTURES = Path(__file__).parent / "fixtures"
MOCK_ISO = Path(__file__).parent.parent / "mock_iso"


@pytest.fixture
def html_response():
    """Build an HtmlResponse from a saved fixture file. Offline, fast, deterministic."""

    def make(name: str, url: str) -> HtmlResponse:
        return HtmlResponse(url=url, body=(FIXTURES / name).read_bytes(), encoding="utf-8")

    return make


@pytest.fixture
def csv_response():
    def make(day: str) -> TextResponse:
        body = (MOCK_ISO / f"prices_{day}.csv").read_bytes()
        url = f"http://127.0.0.1:8765/prices_{day}.csv"
        return TextResponse(url=url, body=body, encoding="utf-8")

    return make


@pytest.fixture
def make_crawler():
    """A real Crawler with a spider attached, so components can use crawler.stats/spider."""

    def make(settings: dict | None = None, spidercls=Spider, **spider_kwargs):
        crawler = get_crawler(spidercls, settings)
        if spidercls is Spider:  # the bare base class needs a name; real spiders define one
            spider_kwargs.setdefault("name", "test")
        # Keyword arguments only, exactly how `scrapy crawl -a key=value` passes them.
        spider = spidercls.from_crawler(crawler, **spider_kwargs)
        crawler.spider = spider
        return crawler, spider

    return make

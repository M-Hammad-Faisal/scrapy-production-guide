"""Downloader middlewares: behaviour that applies to every request or response.

Execution order (lower number = closer to the engine):
  requests go DOWN the list (low -> high), responses come back UP (high -> low).

  450  RotatingUserAgentMiddleware   sets a User-Agent before the built-in one (500)
  460  ProxyMiddleware               sets request.meta["proxy"] before HttpProxyMiddleware (750)
  560  SoftBlockMiddleware           sees the response AFTER HttpCompression (590) has decoded it
"""

from __future__ import annotations

import itertools
import logging
import random

from scrapy import Request
from scrapy.crawler import Crawler
from scrapy.downloadermiddlewares.retry import get_retry_request
from scrapy.exceptions import IgnoreRequest, NotConfigured
from scrapy.http import Response, TextResponse

logger = logging.getLogger(__name__)


class RotatingUserAgentMiddleware:
    """Pick a User-Agent per request from USER_AGENT_POOL.

    Honest advice (docs/04): rotating UAs alone does not defeat bot detection. A Chrome UA with a
    non-Chrome TLS fingerprint is a stronger bot signal than a plain, honest UA. Use this only
    when a site needs variation and you are allowed to access it.
    """

    def __init__(self, pool: list[str], seed: int | None = None):
        self.pool = pool
        self.rng = random.Random(seed)

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        pool = crawler.settings.getlist("USER_AGENT_POOL")
        if not pool:
            raise NotConfigured("USER_AGENT_POOL is empty")
        return cls(pool)

    def process_request(self, request: Request):
        request.headers.setdefault(b"User-Agent", self.rng.choice(self.pool))
        return None


class ProxyMiddleware:
    """Round-robin proxies from PROXY_URLS (comma-separated env var). Secrets stay out of code.

    Set ``meta["no_proxy"]=True`` on a request to bypass. Prefer sticky sessions (one proxy per
    cookiejar) for logged-in crawls; this simple version rotates per request.
    """

    def __init__(self, proxies: list[str]):
        self.cycle = itertools.cycle(proxies)

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        proxies = crawler.settings.getlist("PROXY_URLS")
        if not proxies:
            raise NotConfigured("PROXY_URLS is empty")
        return cls(proxies)

    def process_request(self, request: Request):
        if "proxy" not in request.meta and not request.meta.get("no_proxy"):
            request.meta["proxy"] = next(self.cycle)
        return None


class SoftBlockMiddleware:
    """Detect 'blocked' pages that come back as HTTP 200 and retry them, with a limit.

    The costliest scraping bug is a 200 response containing "verify you are human". Without this,
    the block page flows into the parser and produces empty or garbage rows.
    """

    def __init__(self, crawler: Crawler, markers: list[str], max_retries: int):
        self.crawler = crawler
        self.markers = [m.lower() for m in markers]
        self.max_retries = max_retries

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        markers = crawler.settings.getlist("SOFT_BLOCK_MARKERS")
        if not markers:
            raise NotConfigured("SOFT_BLOCK_MARKERS is empty")
        return cls(crawler, markers, crawler.settings.getint("SOFT_BLOCK_MAX_RETRIES", 2))

    def process_response(self, request: Request, response: Response):
        if response.status != 200 or not isinstance(response, TextResponse):
            return response
        head = response.text[:20000].lower()
        if not any(marker in head for marker in self.markers):
            return response

        stats = self.crawler.stats
        stats.inc_value("soft_block/detected")
        retry = get_retry_request(
            request,
            spider=self.crawler.spider,
            reason="soft_block",
            max_retry_times=self.max_retries,
        )
        if retry is not None:
            return retry
        stats.inc_value("soft_block/gave_up")
        raise IgnoreRequest(f"soft block persisted after retries: {request.url}")

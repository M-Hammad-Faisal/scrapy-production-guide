"""Shared behaviour for every spider. One spider per source, but common plumbing lives here."""

from __future__ import annotations

import scrapy
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.python.failure import Failure


class BaseSpider(scrapy.Spider):
    """Adds an errback that logs and counts failures instead of letting them vanish.

    Gotcha: if a request has no errback, a failure (DNS error, timeout, non-2xx after retries) is
    only a line in the log. Counting it in the stats lets the guard and your alerts see it.
    """

    def errback_log(self, failure: Failure):
        request = failure.request
        if failure.check(HttpError):
            status = failure.value.response.status
            self.crawler.stats.inc_value(f"errback/http_{status}")
            self.logger.warning("HTTP %s for %s", status, request.url)
        else:
            self.crawler.stats.inc_value(f"errback/{failure.type.__name__}")
            # Log the message too: "Error for <url>" alone is useless at 3 a.m.
            self.logger.warning(
                "%s for %s: %s", failure.type.__name__, request.url, failure.getErrorMessage()[:500]
            )

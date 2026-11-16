"""Extensions react to signals. This one is a guard rail: it turns 'ran but produced bad data'
into a clearly failed run.

Why it exists: ``scrapy crawl`` exits 0 even if every callback raised or zero items came back.
The guard records the verdict in the stats, and ``scripts/run_spider.py`` turns it into a
non-zero exit code your scheduler can alert on.
"""

from __future__ import annotations

import logging

from scrapy import Spider, signals
from scrapy.crawler import Crawler
from scrapy.exceptions import NotConfigured

logger = logging.getLogger(__name__)


class GuardExtension:
    """Fail the run when too few items came back, or too many were rejected.

    MIN_ITEMS       minimum number of items that must pass every pipeline (0 disables)
    MAX_DROP_RATIO  maximum share of items dropped by pipelines, 0..1 (0 disables)
    """

    def __init__(self, crawler: Crawler, min_items: int, max_drop_ratio: float):
        self.crawler = crawler
        self.min_items = min_items
        self.max_drop_ratio = max_drop_ratio

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        min_items = crawler.settings.getint("MIN_ITEMS", 0)
        ratio = crawler.settings.getfloat("MAX_DROP_RATIO", 0.0)
        if not min_items and not ratio:
            raise NotConfigured("no guard thresholds configured")
        ext = cls(crawler, min_items, ratio)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_closed(self, spider: Spider, reason: str):
        stats = self.crawler.stats
        scraped = stats.get_value("item_scraped_count", 0)
        dropped = stats.get_value("item_dropped_count", 0)
        problems: list[str] = []

        # A run stopped on purpose (item limit, timeout) is judged on what it did collect.
        if self.min_items and scraped < self.min_items:
            problems.append(f"only {scraped} items, expected at least {self.min_items}")
        total = scraped + dropped
        if self.max_drop_ratio and total and dropped / total > self.max_drop_ratio:
            problems.append(
                f"{dropped}/{total} items dropped ({dropped / total:.0%}), "
                f"limit {self.max_drop_ratio:.0%}"
            )

        if problems:
            stats.set_value("guard/failed", True)
            stats.set_value("guard/reasons", "; ".join(problems))
            logger.error("GUARD FAILED: %s", "; ".join(problems))
        else:
            stats.set_value("guard/failed", False)

"""Item pipelines: validate (100) -> dedupe (200) -> store (300).

Order matters. Validate first so junk never reaches the database and is counted by rule name.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem, NotConfigured

from crawlers import storage
from crawlers.items import BookItem, PriceItem, QuoteItem

logger = logging.getLogger(__name__)

Rule = Callable[[Any], str | None]  # returns an error message, or None when the item is fine


def _book_rules() -> dict[str, Rule]:
    return {
        "title_required": lambda i: None if i.title else "missing title",
        "url_required": lambda i: None if i.url else "missing url",
        "price_positive": lambda i: (
            None if i.price_gbp is not None and i.price_gbp > 0 else "price missing or <= 0"
        ),
        "rating_range": lambda i: (
            None if i.rating is not None and 1 <= i.rating <= 5 else "rating not in 1..5"
        ),
    }


def _quote_rules() -> dict[str, Rule]:
    return {
        "text_required": lambda i: None if i.text else "missing text",
        "author_required": lambda i: None if i.author else "missing author",
    }


def _price_rules() -> dict[str, Rule]:
    return {
        "node_required": lambda i: None if i.node else "missing node",
        "price_required": lambda i: None if i.price_usd_mwh is not None else "missing price",
        # Market prices can be negative, but not absurd. Tune per source.
        "price_sane": lambda i: (
            None
            if i.price_usd_mwh is None or -1000 <= i.price_usd_mwh <= 20000
            else f"price out of range: {i.price_usd_mwh}"
        ),
        "utc_timestamp": lambda i: (
            None
            if i.interval_start_utc.tzinfo is not None
            and i.interval_start_utc.utcoffset().total_seconds() == 0
            else "timestamp is not UTC-aware"
        ),
        # A hand-entered value must say who entered it and why: that is the audit trail.
        "manual_needs_reason": lambda i: (
            None if i.origin != "manual" or (i.reason and len(i.reason.strip()) >= 5)
            else "manual entries need a reason (at least 5 characters)"
        ),
        "manual_needs_author": lambda i: (
            None if i.origin != "manual" or i.entered_by else "manual entries need entered_by"
        ),
    }


RULES: dict[type, dict[str, Rule]] = {
    BookItem: _book_rules(),
    QuoteItem: _quote_rules(),
    PriceItem: _price_rules(),
}


def validate_item(item: Any) -> list[tuple[str, str]]:
    """Run every rule for this item type. Returns [(rule_name, message), ...]; empty means valid.

    This is THE validation function: the Scrapy pipeline below and the manual-entry API both call
    it, so a hand-entered record can never pass checks a scraped record would fail.
    """
    return [
        (name, error)
        for name, rule in RULES.get(type(item), {}).items()
        if (error := rule(item))
    ]


class ValidationPipeline:
    """Reject items that break a named rule, and count each rule separately in the stats."""

    def __init__(self, crawler: Crawler):
        self.stats = crawler.stats

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        return cls(crawler)

    def process_item(self, item):
        problems = validate_item(item)
        if problems:
            name, error = problems[0]
            self.stats.inc_value(f"validation/failed/{name}")
            raise DropItem(f"{name}: {error}")
        self.stats.inc_value("validation/passed")
        return item


KEY_FUNCS: dict[type, Callable[[Any], tuple]] = {
    BookItem: lambda i: (i.url,),
    QuoteItem: lambda i: (i.author, i.text),
    PriceItem: lambda i: (i.source, i.node, i.interval_start_utc),
}


class DedupePipeline:
    """Drop repeats seen earlier in THIS run.

    This is a cheap optimisation, not the source of truth. Across runs, duplicates are handled
    by the database unique key plus upsert (see storage.py).
    """

    def __init__(self, crawler: Crawler):
        self.stats = crawler.stats
        self.seen: set[tuple] = set()

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        return cls(crawler)

    def process_item(self, item):
        key = (type(item).__name__, *KEY_FUNCS[type(item)](item))
        if key in self.seen:
            self.stats.inc_value("dedupe/dropped")
            raise DropItem(f"duplicate in this run: {key}")
        self.seen.add(key)
        return item


class StoragePipeline:
    """Batch items and write them with idempotent upserts, OFF the reactor thread.

    Gotcha this avoids: a synchronous database call inside process_item blocks Scrapy's event
    loop, so every in-flight request stalls. We buffer, and run the blocking write with
    ``asyncio.to_thread`` (Scrapy uses the asyncio reactor, see settings.TWISTED_REACTOR).
    """

    def __init__(self, crawler: Crawler, database_url: str, batch_size: int):
        self.stats = crawler.stats
        self.database_url = database_url
        self.batch_size = batch_size
        self.engine: sa.Engine | None = None
        self.buffer: list[Any] = []

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        url = crawler.settings.get("DATABASE_URL")
        if not url:
            raise NotConfigured("DATABASE_URL is not set; storage pipeline disabled")
        return cls(crawler, url, crawler.settings.getint("STORAGE_BATCH_SIZE", 100))

    def open_spider(self):
        url = sa.engine.make_url(self.database_url)
        if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
            # SQLite creates the file but not its folder; a fresh checkout would crash here.
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = sa.create_engine(self.database_url, pool_pre_ping=True)
        storage.create_all(self.engine)

    async def process_item(self, item):
        self.buffer.append(item)
        if len(self.buffer) >= self.batch_size:
            await self._flush()
        return item

    async def close_spider(self):
        await self._flush()  # never lose the tail of the buffer
        if self.engine is not None:
            self.engine.dispose()

    async def _flush(self) -> None:
        # Swap the buffer first: other coroutines keep appending while we write.
        batch, self.buffer = self.buffer, []
        if not batch:
            return
        assert self.engine is not None
        result = await asyncio.to_thread(storage.write_batch, self.engine, batch)
        self.stats.inc_value("storage/rows_written", result.written)
        self.stats.inc_value("storage/batches")
        if result.skipped:
            # A manual value was protected from being overwritten by the crawl.
            self.stats.inc_value("storage/skipped_manual_override", result.skipped)


__all__ = ["ValidationPipeline", "DedupePipeline", "StoragePipeline", "RULES"]

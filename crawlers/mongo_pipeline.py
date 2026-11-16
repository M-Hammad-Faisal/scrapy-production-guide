"""MongoDB as an alternative (or additional) sink. Same contract as the SQL pipeline:

* idempotent: a unique index on the natural key + ``ReplaceOne(..., upsert=True)``;
* batched and written OFF the reactor thread (``asyncio.to_thread``);
* manual values are protected from being overwritten by a crawl.

Enable it by setting MONGODB_URI (otherwise the pipeline disables itself).

When to choose Mongo over SQL (see docs/02): records with uneven shapes, or raw documents stored
next to parsed fields. For structured, relational, constraint-heavy data, PostgreSQL stays the
better default, and the manual-entry API in this repo writes to SQL.

MongoDB traps this module handles on purpose:

1. ``decimal.Decimal`` cannot be encoded by pymongo. Convert to ``Decimal128`` (never float).
2. pymongo returns NAIVE datetimes unless the client is created with ``tz_aware=True``.
3. A *filtered* upsert (``origin != manual``) that does not match tries to INSERT, which hits the
   unique index and raises E11000. That error is the "protected manual value" signal here, so we
   count it as skipped instead of crashing.
4. ``bulk_write(ordered=False)`` so one conflict does not abort the rest of the batch.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from bson.decimal128 import Decimal128
from pymongo import ASCENDING, MongoClient, ReplaceOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError
from scrapy.crawler import Crawler
from scrapy.exceptions import NotConfigured

from crawlers.items import BookItem, PriceItem, QuoteItem
from crawlers.storage import WriteResult

logger = logging.getLogger(__name__)

DUPLICATE_KEY = 11000

# item class -> (collection, natural key fields)
COLLECTIONS: dict[type, tuple[str, list[str]]] = {
    BookItem: ("books", ["url"]),
    QuoteItem: ("quotes", ["author", "text"]),
    PriceItem: ("iso_prices", ["source", "node", "interval_start_utc"]),
}


def to_document(item: Any) -> dict[str, Any]:
    doc = asdict(item)
    for name, value in doc.items():
        if isinstance(value, Decimal):
            doc[name] = Decimal128(value)  # trap 1
    doc["scraped_at"] = datetime.now(UTC)
    return doc


def build_operations(items: list[Any], *, manual: bool = False) -> dict[str, list[ReplaceOne]]:
    """Group items by collection and build one upsert per natural key (last one wins)."""
    grouped: dict[str, dict[tuple, ReplaceOne]] = {}
    for item in items:
        collection, key = COLLECTIONS[type(item)]
        doc = to_document(item)
        flt: dict[str, Any] = {k: doc[k] for k in key}
        if not manual and "origin" in doc:
            flt["origin"] = {"$ne": "manual"}  # protect hand-entered values (trap 3)
        op = ReplaceOne(flt, doc, upsert=True)
        grouped.setdefault(collection, {})[tuple(doc[k] for k in key)] = op
    return {name: list(ops.values()) for name, ops in grouped.items()}


def ensure_indexes(db: Database) -> None:
    for collection, key in COLLECTIONS.values():
        db[collection].create_index([(k, ASCENDING) for k in key], unique=True, name="natural_key")


def write_batch(db: Database, items: list[Any], *, manual: bool = False) -> WriteResult:
    written = skipped = 0
    for collection, ops in build_operations(items, manual=manual).items():
        try:
            db[collection].bulk_write(ops, ordered=False)  # trap 4
            written += len(ops)
        except BulkWriteError as exc:
            errors = exc.details.get("writeErrors", [])
            if any(e.get("code") != DUPLICATE_KEY for e in errors):
                raise  # a real failure, not a protected manual value
            skipped += len(errors)
            written += len(ops) - len(errors)
    return WriteResult(written=written, skipped=skipped)


class MongoPipeline:
    """Batched, off-thread, idempotent MongoDB writer. Disabled unless MONGODB_URI is set."""

    def __init__(self, crawler: Crawler, uri: str, db_name: str, batch_size: int):
        self.stats = crawler.stats
        self.uri, self.db_name, self.batch_size = uri, db_name, batch_size
        self.client: MongoClient | None = None
        self.db: Database | None = None
        self.buffer: list[Any] = []

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        uri = crawler.settings.get("MONGODB_URI")
        if not uri:
            raise NotConfigured("MONGODB_URI is not set; MongoDB pipeline disabled")
        return cls(
            crawler,
            uri,
            crawler.settings.get("MONGODB_DB", "crawl"),
            crawler.settings.getint("STORAGE_BATCH_SIZE", 100),
        )

    def open_spider(self):
        self.client = MongoClient(self.uri, tz_aware=True, serverSelectionTimeoutMS=5000)  # trap 2
        self.db = self.client[self.db_name]
        ensure_indexes(self.db)

    async def process_item(self, item):
        self.buffer.append(item)
        if len(self.buffer) >= self.batch_size:
            await self._flush()
        return item

    async def close_spider(self):
        await self._flush()
        if self.client is not None:
            self.client.close()

    async def _flush(self) -> None:
        batch, self.buffer = self.buffer, []
        if not batch:
            return
        assert self.db is not None
        result = await asyncio.to_thread(write_batch, self.db, batch)
        self.stats.inc_value("mongo/rows_written", result.written)
        self.stats.inc_value("mongo/batches")
        if result.skipped:
            self.stats.inc_value("mongo/skipped_manual_override", result.skipped)

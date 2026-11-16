"""One ingestion function for data that does not come from a spider.

The manual-entry API (``manual_entry/``) calls ``ingest_manual``. It uses exactly the same
``validate_item`` rules and the same idempotent ``write_batch`` upsert as the Scrapy pipelines,
so a hand-entered record cannot skip a check, and it lands in the same table under the same key.

Differences by design:
* the batch is all-or-nothing: if any record is invalid, nothing is written;
* ``manual=True`` lets the write overwrite scraped values, and marks the row ``origin='manual'``,
  after which later crawls will NOT overwrite it (see storage.upsert_statement).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from crawlers import storage
from crawlers.pipelines import validate_item


@dataclass
class IngestResult:
    written: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)  # [{"index": 0, "rule": ..., ...}]

    @property
    def ok(self) -> bool:
        return not self.errors


def ingest_manual(engine: sa.Engine, items: list[Any]) -> IngestResult:
    result = IngestResult()
    for index, item in enumerate(items):
        for rule, message in validate_item(item):
            result.errors.append({"index": index, "rule": rule, "message": message})
    if result.errors:
        return result  # all-or-nothing: write nothing

    outcome = storage.write_batch(engine, items, manual=True)
    result.written, result.skipped = outcome.written, outcome.skipped
    return result

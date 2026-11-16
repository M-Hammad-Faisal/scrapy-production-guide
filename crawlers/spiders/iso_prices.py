"""A market-data style spider: daily CSV files of hourly prices, with a date-range backfill.

This models the kind of work in docs/05-migration-and-utility-data.md without hitting a real grid
operator. It reads files from a local mock feed (``scripts/serve_mock.py``). A real source would
differ in URL and layout, but the problems are the same:

* Backfill vs incremental: the same spider, different arguments.
    scrapy crawl iso_prices -a start_date=2026-06-15 -a end_date=2026-06-15
* Hour-ending labels and daylight saving (23- and 25-hour days).
* Revised values: an upsert keyed on (source, node, interval_start_utc) makes reruns safe.
* Gap detection: a day with the wrong number of intervals is counted, not filled silently.

CSV columns: date, hour_ending, dst_flag, node, lmp_usd_mwh
  hour_ending  1..24 (25 on the fall-back day) = the END of the local hour interval
  dst_flag     1 for the second occurrence of the repeated hour on the fall-back day, else 0
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from datetime import date, timedelta
from typing import Any

from scrapy import Request
from scrapy.http import TextResponse

from crawlers.items import PriceItem
from crawlers.spiders.base import BaseSpider
from crawlers.utils.parsing import parse_price
from crawlers.utils.timeutils import hours_in_local_day, interval_start_utc


class IsoPricesSpider(BaseSpider):
    name = "iso_prices"

    def __init__(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        source: str = "mockiso",
        tz: str = "America/New_York",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        # Spider arguments (-a) arrive as strings. Convert and validate them here, loudly.
        if not start_date:
            raise ValueError("start_date is required, e.g. -a start_date=2026-06-15")
        self.start_date = date.fromisoformat(start_date)
        self.end_date = date.fromisoformat(end_date) if end_date else self.start_date
        if self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        self.source = source
        self.tz = tz

    async def start(self) -> AsyncIterator[Any]:
        # Never use "today" inside the spider: backfills and reruns must be reproducible.
        base = self.settings.get("ISO_BASE_URL").rstrip("/")
        day = self.start_date
        while day <= self.end_date:
            yield Request(
                f"{base}/prices_{day.isoformat()}.csv",
                callback=self.parse_day,
                errback=self.errback_log,
                cb_kwargs={"local_date": day},
            )
            day += timedelta(days=1)

    def parse_day(self, response: TextResponse, local_date: date) -> Iterator[PriceItem]:
        rows_per_node: Counter[str] = Counter()
        for row in csv.DictReader(io.StringIO(response.text)):
            node = (row.get("node") or "").strip()
            try:
                hour_ending = int(row["hour_ending"])
                second = row.get("dst_flag", "0").strip() == "1"
                start_utc = interval_start_utc(local_date, hour_ending, self.tz, second)
            except (KeyError, ValueError) as exc:
                # A nonexistent or malformed interval is a data problem: count it, keep going.
                self.crawler.stats.inc_value("iso/bad_interval")
                self.logger.warning("bad interval in %s: %s (%s)", response.url, row, exc)
                continue

            rows_per_node[node] += 1
            label = f"{local_date.isoformat()} HE{hour_ending}{'*' if second else ''}"
            yield PriceItem(
                source=self.source,
                node=node,
                interval_start_utc=start_utc,
                interval_minutes=60,
                price_usd_mwh=parse_price(row.get("lmp_usd_mwh")),  # None if "N/A" -> validation
                local_label=label,
            )

        # Gap detection: every node should have 23, 24 or 25 intervals depending on the date.
        expected = hours_in_local_day(local_date, self.tz)
        for node, count in rows_per_node.items():
            if count != expected:
                self.crawler.stats.inc_value("iso/incomplete_day")
                self.logger.warning(
                    "%s %s: %s intervals, expected %s", local_date, node, count, expected
                )

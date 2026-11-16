"""Run a spider and turn a *bad* run into a non-zero exit code.

Why this exists: `scrapy crawl` exits 0 even when callbacks raised or zero items came back. A
scheduler (cron, Airflow, Kubernetes) then thinks everything is fine. This wrapper reads the final
stats and fails loudly.

    python scripts/run_spider.py books --max-items 50
    python scripts/run_spider.py iso_prices -a start_date=2026-06-15 -a end_date=2026-06-16

Exit codes: 0 healthy, 2 unhealthy (details printed as JSON), 1 could not start.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

# finish reasons that mean "stopped on purpose, judge the data we got"
OK_REASONS = {"finished", "closespider_itemcount", "closespider_pagecount"}


def parse_pairs(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"expected KEY=VALUE, got {pair!r}")
        out[key] = value
    return out


def evaluate(stats: dict, max_errors: int, fail_on: list[str] | None = None) -> list[str]:
    problems = []
    for prefix in fail_on or []:
        hits = {k: v for k, v in stats.items() if k.startswith(prefix)}
        if hits:
            problems.append(f"stats that must be zero: {hits}")
    reason = stats.get("finish_reason")
    if reason not in OK_REASONS:
        problems.append(f"finish_reason={reason}")
    if stats.get("guard/failed"):
        problems.append(f"guard: {stats.get('guard/reasons')}")
    errors = stats.get("log_count/ERROR", 0)
    if errors > max_errors:
        problems.append(f"{errors} ERROR log lines (max {max_errors})")
    exceptions = {k: v for k, v in stats.items() if k.startswith("spider_exceptions/")}
    if exceptions:
        problems.append(f"callback exceptions: {exceptions}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spider")
    parser.add_argument("-a", dest="spider_args", action="append", default=[], metavar="K=V")
    parser.add_argument("-s", dest="settings", action="append", default=[], metavar="K=V")
    parser.add_argument("--max-items", type=int, default=0, help="stop after N items (smoke test)")
    parser.add_argument("--max-errors", type=int, default=0)
    args = parser.parse_args()

    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "crawlers.settings")
    settings = get_project_settings()
    for key, value in parse_pairs(args.settings).items():
        settings.set(key, value, priority="cmdline")
    if args.max_items:
        settings.set("CLOSESPIDER_ITEMCOUNT", args.max_items, priority="cmdline")

    process = CrawlerProcess(settings)
    try:
        crawler = process.create_crawler(args.spider)
        process.crawl(crawler, **parse_pairs(args.spider_args))
    except Exception as exc:  # unknown spider, bad arguments
        print(f"could not start: {exc}", file=sys.stderr)
        return 1
    process.start()

    stats = crawler.stats.get_stats()
    problems = evaluate(stats, args.max_errors, settings.getlist("FAIL_ON_STATS"))
    summary = {
        "spider": args.spider,
        "finish_reason": stats.get("finish_reason"),
        "items": stats.get("item_scraped_count", 0),
        "dropped": stats.get("item_dropped_count", 0),
        "rows_written": stats.get("storage/rows_written", 0),
        "mongo_rows_written": stats.get("mongo/rows_written", 0),
        "skipped_manual_override": stats.get("storage/skipped_manual_override", 0),
        "problems": problems,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

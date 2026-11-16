# Migrating scrapers to Python, and utility/market data

A practical guide to a common kind of data-engineering work: moving existing crawlers from one language onto a standard Python/Scrapy system, extending them with extra fields for new and historical data, adding crawlers for new sources, and building a way to add data by hand.

Domain facts below are general. Confirm the details of any real source against its own documentation.

## Migration playbook: Go to Python without losing data

1. **Inventory.** For each scraper: source URL or API, schedule, output fields and types, how it handles errors, where output goes, who consumes it.
2. **Freeze a golden dataset.** Run the old scraper and keep its output (files or table snapshots) for a set of dates. This is your truth.
3. **Write the field mapping** in a document: old field, new field, type, unit, timezone, nullability. Ambiguity found here costs minutes; found later it costs data.
4. **Build the new spider** to produce the same fields. Reuse the project's base spider, item, pipeline and tests.
5. **Shadow run.** Run both side by side on the same sources and dates. Write a **diff tool** that compares row by row on the unique key and reports missing rows, extra rows and changed values.
6. **Explain every difference.** Either the new one is wrong (fix it) or the old one was wrong (document it, get sign-off).
7. **Add the new fields** only after parity. Do not change behaviour and add fields in the same step.
8. **Backfill.** Run history in date chunks, resumable, throttled, idempotent.
9. **Cut over** one source at a time. Keep the old scraper runnable and a rollback plan for a defined period.
10. **Retire** the old code once the new one has run clean for an agreed window.

What goes wrong: rounding and unit differences, timezone handling that differed silently, "empty" being `0` in one system and `NULL` in another, and pagination limits the old code handled quietly.

## Adding new fields for new and historical data

- Version the schema. Add nullable columns first, then backfill, then add constraints.
- Historical pages may have a different layout from today's. Keep **per-layout parsers** selected by date or by a layout marker, with fixtures for each.
- Backfills need rate control and progress tracking (a table of `(source, date, status)`), so a failure resumes instead of restarting.

## A manual-entry toolset that follows the same process as scraped data

The principle: a manual record must not bypass the checks. A good design:

- One **ingestion function** (`ingest(record, origin)`) used by both the spiders (through the pipeline) and the manual tool.
- The same **validation** rules and the same **unique key** and upsert.
- An `origin` field (`scraped` or `manual`) and `entered_by`, `entered_at`, `reason` for audit.
- Entry through a small DRF endpoint, a Django admin form, or a CSV upload that goes through the same ingestion function.
- Manual values should not be silently overwritten by the next crawl: decide a precedence rule (for example manual wins until released) and document it.

## ISO/RTO and market data: what to know

An **ISO** (independent system operator) or **RTO** (regional transmission organization) runs a power grid and its wholesale market. Examples include PJM, MISO, ERCOT, CAISO, NYISO, ISO-NE and SPP. They typically publish prices, load, generation and outage data, often through official downloads or APIs, with reports in CSV, JSON, XML or PDF.

Things that matter for correctness:

| Topic | Why it matters |
|---|---|
| Intervals | Hourly, 15-minute and 5-minute data exist. Store `interval_start_utc` and the interval length |
| Hour ending | Many markets label an interval by its **end** hour. Off-by-one-hour bugs are common |
| Daylight saving | 23-hour and 25-hour days. Local-time keys collide on fall-back day |
| Revisions | Prices are often preliminary then settled. Upsert, keep `scraped_at` and consider storing versions |
| Nodes and zones | Many series per interval. The key includes the node or zone |
| Units | $/MWh, MW, MWh. Store the unit with the value, convert once |
| Publishing delay | Data appears late and sometimes out of order. Incremental runs should re-read a recent window |
| Gaps | A missing interval is information. Detect and alert, do not fill silently |

The demo `iso_prices` spider and `utils/timeutils.py` cover intervals, hour-ending conversion and the daylight-saving cases against a local mock feed.

## Canadian utility commission filings

Regulators publish dockets, decisions, rate cases and tariff filings, often as PDFs behind a search interface. Typical approach:

1. Enumerate dockets (listing pages, search results or an index feed) with a normal spider.
2. Download each document, **store the original file** (hash it), and record the source URL and fetch time.
3. Extract text and tables in a separate step (a PDF extraction service or library), validate, and write structured fields.
4. Handle both English and French sources where regulators publish in both.

Keeping extraction separate from crawling means you can fix a parser and reprocess stored files without hitting the regulator's site again.

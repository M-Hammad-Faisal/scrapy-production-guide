# Scrapy production guide

A complete, runnable Scrapy project built to **learn Scrapy properly** and to show how a crawling pipeline is built for production: validation, idempotent storage, soft-block handling, guard rails, tests on saved fixtures, and a runner that fails loudly when a run is bad.

It comes with a guide that says **when to use what** and **what goes wrong in production**. Everything was run against real practice sites (`books.toscrape.com`, `quotes.toscrape.com`), not just written.

> Nothing here scrapes anything you are not allowed to. The practice sites exist for this purpose. Before pointing any spider at a real source, read its terms and robots.txt, and prefer an official API or bulk download.

## What is in it

| Spider | Teaches | Run it |
|---|---|---|
| `books` | Listing then detail pages, pagination, `ItemLoader`, `cb_kwargs`, errbacks, contracts | `make crawl-books` |
| `quotes_crawl` | `CrawlSpider` rules (and the anchored-regex bug) | `make crawl-quotes-crawl` |
| `quotes_api` | Finding the JSON endpoint behind a page; computed start requests | `make crawl-quotes-api` |
| `quotes_js` | JavaScript rendering with Playwright, the last resort | `make` target not provided; see its docstring |
| `iso_prices` | Market-style time series: backfills, hour-ending labels, daylight saving, gap detection, revisions | `make crawl-iso`, `make crawl-iso-dst` |

| Component | File | Why it exists |
|---|---|---|
| Settings | `crawlers/settings.py` | Every non-default value explained |
| Items | `crawlers/items.py` | Typed dataclass items, two styles |
| Loader | `crawlers/loaders.py` | Cleaning separated from validation |
| Validation, dedupe, storage | `crawlers/pipelines.py` | Rules counted by name; batched, off-thread upserts |
| Storage | `crawlers/storage.py` | Natural keys + `ON CONFLICT DO UPDATE` (SQLite and PostgreSQL) |
| Middlewares | `crawlers/middlewares.py` | Soft-block detection with retry limit, UA pool, proxy rotation |
| Guard extension | `crawlers/extensions.py` | Fails a run on too few items or too many drops |
| MongoDB sink | `crawlers/mongo_pipeline.py` | Batched, idempotent, manual-protected; handles Decimal128, tz-aware times, E11000 |
| Manual-entry API | `manual_entry/`, `crawlers/ingest.py` | DRF endpoints using the same validation and upsert as the scrapers, with an audit trail and "manual wins" |
| Runner | `scripts/run_spider.py` | Turns a bad run into exit code 2 (`scrapy crawl` returns 0) |
| Time utilities | `crawlers/utils/timeutils.py` | Hour-ending to UTC, 23- and 25-hour days |

## Quick start

Needs Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
make setup           # virtualenv + dependencies
make test            # 82 offline tests, no network
make test-integration # 10 tests against real PostgreSQL + MongoDB (needs Docker)
make api             # manual-entry API on :8000 (demo key alice / s3cret)
make crawl-books     # 50 real books -> validated -> data/crawl.db
make crawl-iso       # mock market feed, includes deliberately bad rows
make shell           # selector playground on books.toscrape.com
```

Run any spider through the wrapper to get a verdict and an exit code:

```bash
.venv/bin/python scripts/run_spider.py books --max-items 50
echo $?   # 0 healthy, 2 unhealthy, 1 could not start
```

PostgreSQL instead of SQLite:

```bash
make db-up
export DATABASE_URL=postgresql+psycopg://crawler:crawler@localhost:5432/crawl
.venv/bin/python scripts/run_spider.py books --max-items 50
```

## The guide (read in this order)

| Doc | Read it to learn |
|---|---|
| [`docs/00-learning-path.md`](docs/00-learning-path.md) | A 2-day plan, then 3 days of exercises |
| [`docs/01-core-concepts.md`](docs/01-core-concepts.md) | The request lifecycle, selectors, items, pipelines, settings precedence |
| [`docs/02-when-to-use-what.md`](docs/02-when-to-use-what.md) | Decision tables: spider type, where logic belongs, browser or not, storage, scheduling |
| [`docs/03-production-gotchas.md`](docs/03-production-gotchas.md) | What breaks in production, with a final checklist |
| [`docs/04-bot-protection-and-browsers.md`](docs/04-bot-protection-and-browsers.md) | Escalation ladder, soft blocks, Selenium and Playwright with Scrapy |
| [`docs/05-migration-and-utility-data.md`](docs/05-migration-and-utility-data.md) | Migrating scrapers between languages, manual-entry tooling, market and regulator data |
| [`docs/07-bugs-found-while-building.md`](docs/07-bugs-found-while-building.md) | Real bugs found by running this against live sites and real databases |
| [`docs/08-manual-entry-api-and-mongodb.md`](docs/08-manual-entry-api-and-mongodb.md) | The manual-entry design, when to pick MongoDB, and its traps |

## Honest limits

- PostgreSQL 16 and MongoDB 7 were verified against real servers in Docker (integration tests plus an end-to-end run). Nothing was run against a managed cloud database.
- `quotes_js` needs `playwright install chromium`. It was checked up to browser launch.
- It is a learning project. It has not run at production scale.

## Tests

`make test` runs 82 tests offline against saved HTML and CSV fixtures. `make test-integration` runs 10 more against real PostgreSQL and MongoDB in Docker. Scrapy deprecation warnings are treated as errors so API changes in new Scrapy versions show up in CI. `make check` runs the Scrapy contracts against the live practice site.

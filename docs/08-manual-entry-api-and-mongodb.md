# Manual-entry API (Django REST Framework) and MongoDB

Two pieces that real data projects need and tutorials skip:

1. **A way to add or correct data by hand** that follows the same rules as scraped data.
2. **A second kind of database**, and an honest view of when it is the right choice.

## Part 1: the manual-entry API

### The problem

Scrapers are wrong sometimes. A source publishes a bad value, a page is missing, a regulator sends a correction by email. Someone has to fix the data by hand. The dangerous way to do it is a SQL `UPDATE` in a console: no validation, no record of who changed what, and the next crawl silently overwrites the fix.

### The design

```
 scrapers ──▶ ValidationPipeline ─┐
                                  ├─ validate_item()  ◀── ONE set of rules
 manual API ─▶ ingest_manual() ───┘
                  │
                  ▼
        storage.write_batch(...)  ── ONE idempotent upsert, same table, same unique key
```

| Requirement | How it is met | Where |
|---|---|---|
| A manual record cannot bypass the checks | The API calls the **same** `validate_item()` the scrapers use | `crawlers/pipelines.py`, `crawlers/ingest.py` |
| Same table, same key, no duplicates | The API uses the same `write_batch` upsert | `crawlers/storage.py` |
| Audit trail | Every row has `origin`, `entered_by`, `reason`, `scraped_at` | `PriceItem`, `iso_prices` |
| `entered_by` cannot be faked | It comes from the API key, never from the request body | `manual_entry/auth.py` |
| A reason is mandatory | Rule `manual_needs_reason` | `crawlers/pipelines.py` |
| A later crawl must not undo a manual fix | `ON CONFLICT DO UPDATE ... WHERE origin <> 'manual'` | `storage.upsert_statement` |
| A manual entry may correct a scraped value | `manual=True` skips that `WHERE` | `storage.write_batch` |
| Bulk uploads do not half-apply | Validate everything first, write nothing if anything fails | `ingest_manual` |
| Naive timestamps are not guessed | The serializer demands an explicit offset | `manual_entry/serializers.py` |

### Try it

```bash
make db-up                      # optional: use PostgreSQL (otherwise SQLite)
make api                        # http://127.0.0.1:8000, demo key: alice / s3cret

curl -s -X POST http://127.0.0.1:8000/api/prices/ \
  -H 'X-API-Key: s3cret' -H 'Content-Type: application/json' \
  -d '{"source":"mockiso","node":"HUB_A","interval_start_utc":"2026-06-15T04:00:00Z",
       "price_usd_mwh":"41.25","reason":"settlement correction, ticket 4812"}'

curl -s 'http://127.0.0.1:8000/api/prices/?origin=manual' -H 'X-API-Key: s3cret'
```

Then rerun `make crawl-iso`: the crawl refreshes scraped rows but leaves your manual value alone, and `storage/skipped_manual_override` in the run stats tells you it did so.

### Design decisions worth being able to explain

- **Why not just let people edit the table?** No validation, no audit, and the next crawl erases the fix.
- **Why "manual wins"?** A person corrected something for a reason. If the crawl always overwrote them, corrections would silently vanish. The cost: if the source later publishes a real correction, a manual value stays until someone releases it. Decide your release policy (for example, expire manual overrides after a set time, or require a ticket to remove one).
- **Why is the rule in SQL?** Doing "read, check, write" in Python is a race between the crawler and a person. A single `INSERT ... ON CONFLICT ... WHERE` statement is atomic.
- **Why a plain `CharField` for the timestamp?** DRF's `DateTimeField` silently assumes a timezone for naive input. For market data that is silent corruption. The API refuses ambiguity.

### What this demo is not

- Authentication is API keys read from an environment variable, to keep the demo small. A real deployment uses your company's SSO or Django's own auth, over HTTPS, with per-user permissions.
- There is no UI, rate limiting, or update/delete endpoint. A "release a manual override" operation would be the natural next endpoint.
- It targets the SQL table. The Mongo pipeline is a crawl sink, not a manual-entry target.

## Part 2: MongoDB

### When to choose it

| Choose PostgreSQL when... | Choose MongoDB when... |
|---|---|
| Data is structured and you query across tables | Records vary in shape and a schema would be mostly optional columns |
| You need constraints, joins, transactions, strict types | You store the raw document next to the parsed fields |
| Analysts will write SQL against it | Reads are mostly "fetch this document by key" |
| Money and measurements must be exact | You still need exactness, but you accept the extra care below |

For the data in this repo (typed, keyed, queried by time range) PostgreSQL is the better fit. Mongo is included because teams use both, and because the **idempotency, batching and manual-protection ideas are the same**.

### The pipeline

`crawlers/mongo_pipeline.py` has the same contract as the SQL pipeline: batched writes off the reactor thread, a unique index on the natural key, idempotent upserts, and manual-value protection. It disables itself unless `MONGODB_URI` is set.

```bash
make db-up
export MONGODB_URI=mongodb://localhost:27017
.venv/bin/python scripts/run_spider.py iso_prices -a start_date=2026-06-15   # writes to SQL and Mongo
```

### Four MongoDB traps (all handled and tested)

1. **`Decimal` cannot be stored.** pymongo refuses `decimal.Decimal`. The tempting fix is `float`, which loses exactness. Use `Decimal128`.
2. **Timezones come back naive** unless the client is created with `tz_aware=True`. Without it, a UTC timestamp silently becomes a "local" time on read.
3. **A filtered upsert that does not match tries to insert.** To protect manual values, the scraper's filter says `origin != 'manual'`. When a manual row exists, the filter matches nothing, Mongo tries to insert a new document, and the unique index raises `E11000 duplicate key`. That error is the "protected" signal here, so the pipeline counts it as skipped. A plain `except Exception` would have hidden real failures; it only accepts code 11000 and re-raises anything else.
4. **One conflict must not abort the batch.** `bulk_write(ordered=False)` keeps writing the other documents. The integration test proves the unprotected row is still written.

### Tests

| What | How |
|---|---|
| Document shape, grouping, filters | Offline unit tests (`tests/test_mongo_ops.py`) |
| API behaviour, auth, precedence | Offline, SQLite (`tests/test_manual_entry_api.py`) |
| Real PostgreSQL and MongoDB behaviour | `make test-integration` (starts Docker containers) |

The integration tests exist because the behaviours that matter (how a skipped conflict is counted, what a duplicate key in one batch does, how a filtered upsert fails) differ per engine and cannot be mocked honestly.

## A schema-change gotcha you will hit

`metadata.create_all()` creates missing tables but **never alters existing ones**. When columns `origin`, `entered_by` and `reason` were added to `iso_prices`, any database created earlier kept the old table, and writes failed with "column does not exist". For a learning project, drop the table and recreate it. In production use a migration tool (Alembic for SQLAlchemy) with versioned, reviewed migrations: add nullable columns first, backfill, then add constraints.

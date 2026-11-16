# Production gotchas

Each item is something that bites teams in production. The ones marked **(demo)** are demonstrated in this repo.

## 1. The run "succeeded" but the data is wrong

- **`scrapy crawl` exits with code 0 even when callbacks raised exceptions or zero items came back.** The exit code only reflects a failure to start. Check the stats yourself. **(demo: `scripts/run_spider.py`, `extensions.GuardExtension`)**
- A site redesign changes one selector. `.get()` returns `None`, the field is empty, and nothing crashes. Validate required fields in a pipeline and alert on the drop rate. **(demo: `ValidationPipeline`)**
- Zero items is the most common failure and the quietest. Set a **minimum item count** per spider and fail the run below it.
- HTTP 200 does not mean success. Many sites return a "verify you are human" page with status 200. Detect it from the body. **(demo: `SoftBlockMiddleware`)**
- Silent filtering: the **dupefilter drops repeated requests** without an error. A spider that "stops early" is often a pagination request that looks like one already seen. Use `dont_filter=True` deliberately and log `dupefilter/filtered`.

## 2. Blocking the event loop

- Scrapy is single-threaded and event-driven. A `requests.get()`, a blocking database insert, a `time.sleep()` or a Selenium call inside a callback or pipeline **freezes every in-flight request**. Throughput collapses and timeouts appear for no visible reason.
- Fix: use Scrapy's own requests, push blocking calls to a thread (`asyncio.to_thread` with the asyncio reactor, or Twisted's `deferToThread`), or use an async library. **(demo: `StoragePipeline` buffers items and writes each batch with `asyncio.to_thread`)**
- Heavy parsing (huge PDFs, big pandas jobs) also blocks. Offload it.

## 3. Memory and queue growth

- A spider that yields millions of requests keeps them in memory. Set `JOBDIR` so the queue lives on disk, and use `MEMUSAGE_LIMIT_MB` as a safety net.
- Do not store whole responses or selectors in `meta`. They stay alive as long as the request does.
- Large feeds: write JSON Lines, not a single JSON array (a crashed run leaves invalid JSON).

## 4. Idempotency and reruns

- A rerun, a retry or a backfill will see rows you already have. Without a unique key and an upsert you get duplicates.
- Choose the key from the data, not from the crawl: for time series use `(source, series_id, interval_start_utc)`. **(demo: unique key + `ON CONFLICT DO UPDATE`)**
- Source values get **revised**. Upsert and keep a `scraped_at` so you know which version you hold.
- Separate the **daily incremental** from the **historical backfill**. Same code, different arguments (`-a start_date=... -a end_date=...`), and resumable by date. **(demo: `iso_prices`)**

## 5. Time and timezones (critical for market and utility data)

- Store **UTC**. Also store the original timezone or the original string for audit.
- Daylight saving: one day a year has **23 hours**, another has **25**. A naive "hours 1..24" loop creates a missing or duplicate interval, and a unique key on local time will silently overwrite a row on fall-back day. **(demo: `utils/timeutils.py` and its tests)**
- "Hour ending 1" means the interval **ending** at 01:00, not starting. Know which convention each source uses and convert on ingest.
- Never use `datetime.now()` for business dates inside a spider. Pass the date as an argument.

## 6. Selectors that rot

- `//div[3]/span[2]` breaks the day someone adds a banner. Prefer stable hooks: ids, `data-*` attributes, semantic classes.
- Keep selectors in one place per page type, cover them with **saved HTML fixtures** and unit tests, and refresh the fixtures when the site changes. **(demo: `tests/fixtures`)**
- `//` versus `.//`: searching inside a selected node needs `.//`. The wrong one returns data from elsewhere on the page.

## 7. Politeness, retries and bans

- Defaults are aggressive. Turn on AutoThrottle, lower per-domain concurrency, and set `DOWNLOAD_TIMEOUT` (default 180 s is far too long).
- Retries multiply load: 3 retries on a failing site is 4x the traffic. Retry only transient codes (429, 5xx, timeouts) with a limit.
- Respect `Retry-After` on 429. Backing off is cheaper than being banned.
- Obey robots.txt and the terms of use. For public data (grid operators, regulators), prefer their **official API or bulk download**, which is more stable and legitimate than scraping HTML.

## 8. Sessions, cookies and logins

- Cookies are per spider by default and shared across requests. For several accounts use the `cookiejar` meta key to separate sessions.
- A login that expires mid-crawl: detect the redirect to the login page in a middleware, re-authenticate, and retry the request. Do not let the spider carry on parsing the login page.
- Never log passwords or tokens. Scrapy logs headers on debug; set `LOG_LEVEL=INFO` in production.

## 9. Browser rendering costs

- `scrapy-playwright` needs the asyncio reactor, a low concurrency (browsers eat memory) and **explicit page closing** when you use `playwright_include_page`, or pages leak until the process dies.
- Selenium inside Scrapy blocks the reactor. Keep it for login or token steps, and hand cookies to normal requests.
- A browser is 10 to 100 times slower than plain HTTP. Always look for the JSON call first.

## 10. Operations

- **Structured logs and stats:** read `finish_reason`, `item_scraped_count`, `item_dropped_count`, `log_count/ERROR`, `response_received_count`, and `httpcache` stats at the end of every run. Ship them somewhere.
- **Dev cache only in dev:** `HTTPCACHE_ENABLED` is great while building selectors and dangerous in production (stale pages).
- **Pin versions.** Scrapy, Twisted and the browser libraries move. Commit a lockfile, run CI, and upgrade on purpose.
- **Secrets** (proxies, database URLs) come from environment variables, never from the repo. **(demo: `.env.example`)**
- **Contracts and tests:** unit-test parsers on fixtures (fast, offline) and run `scrapy check` or a nightly live smoke test (catches site changes).
- **Raw data retention:** keep the raw response (or raw file) for a period. When a parser bug is found later you can reprocess without recrawling.
- **One spider, one source.** A shared base class for common behaviour, but separate spiders so one site's change does not break another.

## 11. Gotchas this repo actually hit

Six real bugs found by running against live sites (loose link rules, SQLite folder, silent errbacks, contracts and `cb_kwargs`, gap days not failing a run, and more) are written up with fixes in `07-bugs-found-while-building.md`. Read it after this page.

## Production checklist

- [ ] Selectors covered by fixture tests
- [ ] Required fields validated; invalid items dropped and counted
- [ ] Unique key + upsert; rerun produces no duplicates
- [ ] Minimum item count guard; run exits non-zero when violated
- [ ] AutoThrottle on; sane concurrency and timeouts; robots.txt and terms respected
- [ ] No blocking calls on the reactor thread
- [ ] Time stored in UTC; DST day tested
- [ ] Soft-block detection and retry with limits
- [ ] Secrets from environment; `LOG_LEVEL=INFO`
- [ ] Stats shipped and an alert on failure or low volume
- [ ] Dependencies pinned; CI runs the tests

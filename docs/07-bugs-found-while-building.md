# Bugs found while building this repo

These were found by running the project against real sites, not by reading documentation. Each one is a real production gotcha, and each now has a test or a guard. They are useful precisely because they are real: none were invented to make a point.

## 1. An unanchored link rule crawled the wrong half of the site

**Symptom.** `quotes_crawl` produced 342 items for a site with 100 quotes. The duplicate-dropping pipeline discarded 242 of them, the drop-ratio guard flagged 71% dropped, and the runner exited with code 2.

**Cause.** `LinkExtractor(allow=r"/page/\d+/")`. `allow` is a regular-expression **search**, not a full match. It matched `/page/2/` but also `/tag/love/page/2/`, so the spider crawled every tag listing.

**Fix.** Anchor the pattern to the whole URL: `^https://quotes\.toscrape\.com/page/\d+/$`. A test feeds the rule a page with both kinds of link and checks that only the main pagination is followed.

**Lesson.** Rules and selectors that are too loose do not crash. They collect too much. The guard and the dedupe counter caught it. Without the guard the database would still have been correct (upserts), but the crawl would have hit the site three times as hard as intended.

**Still true after the fix:** `quotes_crawl` drops 10 items as duplicates, because the start page `/` and `/page/1/` are the same page at two URLs. This is expected, not a bug, and it shows why in-run dedupe exists.

## 2. SQLite does not create the folder

**Symptom.** A fresh checkout crashed with `sqlite3.OperationalError: unable to open database file` on the first live run, after all unit tests had passed.

**Cause.** The default `DATABASE_URL` points to `data/crawl.db`. SQLite creates the file, not its directory. The tests used a temporary directory that already existed.

**Fix.** The storage pipeline creates the parent directory for SQLite URLs. A regression test uses a path whose folders do not exist.

**Lesson.** Tests that always run in a pre-made temporary directory hide first-run problems. Run the real thing from a clean state.

## 3. A failing request told you nothing

**Symptom.** The Playwright spider failed with the log line `Error for https://quotes.toscrape.com/js/`. The real cause (a missing browser build) was nowhere.

**Fix.** The errback now logs the exception message as well as its type.

**Lesson.** An errback that logs only the exception class is nearly useless when you are woken up by an alert.

## 4. Scrapy contracts cannot pass `cb_kwargs`

**Symptom.** `scrapy check books` failed with `parse_book() missing 1 required positional argument: 'list_url'`.

**Cause.** Contracts call the callback with only the response. The callback took a `cb_kwargs` argument without a default.

**Fix.** Give callback arguments that come from `cb_kwargs` a default value.

**Lesson.** Passing your own data through `cb_kwargs` is the right design, but remember what else calls your callbacks (contracts, `scrapy parse`).

## 5. A missing file and a gap day did not fail the run

**Symptom.** An `iso_prices` run over three days finished with "problems: none" even though one day's file returned 404 and another day was missing an hour.

**Cause.** The spider counted both in the stats, but nothing turned those counters into a failure.

**Fix.** `FAIL_ON_STATS` in settings lists stat prefixes that must be zero (`errback/`, `iso/incomplete_day`, `iso/bad_interval`, `soft_block/gave_up`). The runner reads it and exits non-zero. The rerun now exits 2.

**Lesson.** Counting a problem is not the same as acting on it. Decide up front which counters mean "the data may be wrong" and wire them to the exit code.

## 6. Smaller things worth knowing

- **`CLOSESPIDER_ITEMCOUNT` is approximate.** Asking for 45 items returned 52, because requests already in flight finish. Use it for smoke tests, not for exact limits.
- **Deprecated feed option.** `overwrite=False` in `FEEDS` printed a deprecation warning. The tests treat Scrapy deprecation warnings as errors (`filterwarnings`), which is how component-signature changes in newer Scrapy versions were caught early.
- **Modern component signatures.** In current Scrapy, components no longer receive `spider` as an argument. Keep the `crawler` from `from_crawler` and use `crawler.spider`, `crawler.stats` and `crawler.settings`.
- **PostgreSQL rejects a multi-row upsert that contains the same key twice** ("cannot affect row a second time"). `write_batch` collapses duplicates within a batch first.
- **Negative prices are valid in power markets.** The validation rule allows them. A rule that says "price must be positive" would have silently dropped real data.

## What was not verified

Being straightforward about limits:

- **PostgreSQL was verified live** (postgres:16 via `make db-up`): three ISO days were crawled twice each and the table held exactly the expected 142 distinct rows, so reruns are idempotent. The repeated fall-back hour was stored as two UTC instants and a legitimate negative price was kept.
- The **`quotes_js` Playwright spider** loads, launches the browser handler and reports failure correctly, but it did not complete a crawl because the browser build it needs was not installed. Run `playwright install chromium` and try it.
- Nothing here was run at production scale. It is a learning project with real mechanics, not a claim of production operations.

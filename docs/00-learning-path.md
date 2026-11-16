# Learning path

How to use this repo to go from "never ran Scrapy in production" to "I built and operated a Scrapy pipeline". Every step points at working code you can run and break.

You already know scraping from Playwright, Puppeteer and Patchright. Scrapy is a different shape: it is an **asynchronous crawling framework** (Twisted) with a fixed request lifecycle, not a browser driver. Most of the learning is the lifecycle and the settings.

## Day 1: get the model right (about 4 hours)

| Step | Do this | Where |
|---|---|---|
| 1 | Read `01-core-concepts.md`, then run `make setup && make shell` and poke at `books.toscrape.com` with `response.css(...)` | docs/01 |
| 2 | Run the `books` spider. Read `crawlers/spiders/books.py` top to bottom. Change one selector and watch the validation pipeline catch it | `make crawl-books` |
| 3 | Read the item loader (`loaders.py`) and the validation pipeline (`pipelines.py`) | |
| 4 | Run the unit tests. Break a selector in the fixture and see which test fails | `make test` |
| 5 | Open `settings.py` and read every comment. Change `CONCURRENT_REQUESTS` and `DOWNLOAD_DELAY`, rerun, compare the stats | |

Goal by end of day: you can explain the request lifecycle (spider, engine, scheduler, downloader, middlewares, pipelines) from memory.

## Day 2: the production parts (about 4 hours)

| Step | Do this | Where |
|---|---|---|
| 6 | Run `quotes_api`. Notice it has no HTML parsing. This is the "find the real API first" lesson | `make crawl-quotes-api` |
| 7 | Run the mock ISO price spider, then open `tests/test_parsing_and_time.py` and read the daylight-saving cases | `make crawl-iso` |
| 8 | Read `middlewares.py` (soft-block detection, UA rotation, proxy) and `extensions.py` (minimum item guard) | |
| 9 | Run `scripts/run_spider.py` with a bad selector and see the non-zero exit code | |
| 10 | Read `03-production-gotchas.md` start to finish, then tick the checklist at the end | docs/03 |
| 11 | Read `07-bugs-found-while-building.md`. Re-create one bug on purpose (loosen the `quotes_crawl` regex, delete `data/`, remove a fixture selector) and watch which guard catches it | docs/07 |

Good "break it" exercises: change `price_gbp_in` so it returns text, point `iso_prices` at a date with no file, set `MIN_ITEMS=1000`, or make the validation rule too strict. Each one should fail loudly in a different place.

Goal by end of day: you can say what you built, what broke, and how you would monitor it.

## Days 3 to 5: make it yours

- Add a second ISO-style source to `iso_prices` with a different timezone and a different file layout. Add a test.
- Switch storage to PostgreSQL with `docker compose up -d db` and set `DATABASE_URL`. Rerun twice and confirm no duplicate rows.
- Run `make api`, enter a price by hand with the curl example in `08-manual-entry-api-and-mongodb.md`, then rerun `make crawl-iso` and confirm the crawl does not overwrite it.
- Run `make test-integration` and read `tests/test_integration.py`: it shows how PostgreSQL and MongoDB differ in ways mocks cannot.
- Add a Playwright spider for `quotes.toscrape.com/js/` (see `quotes_js.py`) and measure how much slower it is than the API spider.
- Write a spider for a real public source you care about, after reading its terms and robots.txt.

## Describing this project honestly

Only claim what you did:

> I built a Scrapy project with spiders for static HTML, a JSON API and a CSV feed, an item pipeline that validates and upserts into PostgreSQL, middlewares for soft-block detection and proxy rotation, and tests on saved HTML fixtures. I also handled daylight-saving time in time-series data.

Then say what you did **not** do: no production traffic, no scheduling at scale, no cloud deployment. Honest boundaries are more credible than inflated claims.

# When to use what

Decision tables. Each row names the example in this repo.

## Which kind of spider?

| Situation | Use | Example here |
|---|---|---|
| Listing pages plus detail pages, you control the navigation | `scrapy.Spider` with `response.follow` | `books` |
| Many pages that follow a link pattern, little per-page logic | `CrawlSpider` with `Rule` and `LinkExtractor` | `quotes_crawl` |
| The site publishes a sitemap | `SitemapSpider` (fastest way to enumerate URLs) | see snippet below |
| The page fills itself from a JSON/XHR call | A normal spider that requests the **JSON endpoint** and parses `response.json()` | `quotes_api` |
| A downloadable CSV/Excel/XML feed | A spider that requests the file and parses rows | `iso_prices` |
| Content only exists after JavaScript runs and has no clean API | Browser rendering (Playwright) for that request only | `quotes_js` |

```python
from scrapy.spiders import SitemapSpider

class ShopSpider(SitemapSpider):
    name = "shop"
    sitemap_urls = ["https://example.com/sitemap.xml"]
    sitemap_rules = [("/product/", "parse_product")]
```

**Rule of thumb:** try them in this order: official API or bulk file, then JSON behind the page, then plain HTML, and only then a browser. Each step down is slower, costlier and more fragile.

## Where does this logic belong?

| You want to... | Put it in |
|---|---|
| Extract a field from HTML | The spider callback |
| Clean a raw value (strip, parse a price) | An `ItemLoader` or a small function in `parsing.py` |
| Reject records that break a rule | A validation **pipeline** |
| Drop records already seen this run | A dedupe pipeline (cross-run dedupe belongs in the database: unique key) |
| Write to a database or file | A storage pipeline (batched, off the reactor thread) |
| Change every request (headers, proxy, auth) | A **downloader middleware** |
| Detect a block page that returns HTTP 200 | A downloader middleware (`process_response`) |
| Stop or alert when too few items came back | An **extension** (listens to `spider_closed`) |
| Run something before/after every crawl | A wrapper script (`scripts/run_spider.py`) |

Pipelines see **items**. Middlewares see **requests and responses**. Extensions see **events**. If you are reaching for `response` inside a pipeline, you are in the wrong place.

## Items: dataclass, Item, or dict?

| Option | Use when |
|---|---|
| `@dataclass` | Default. Typed, readable, IDE-friendly |
| `scrapy.Item` | You need Scrapy's field metadata or older tooling |
| `dict` | Quick scripts only. No structure, typos become silent bugs |

## Concurrency and politeness settings

| Setting | What it does | Typical production choice |
|---|---|---|
| `CONCURRENT_REQUESTS` | Global parallel requests | 16 for one site, more across many sites |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | Parallel requests per domain | 2 to 8; lower when the site is small or fragile |
| `DOWNLOAD_DELAY` | Fixed delay between requests per domain | 0.5 to 2 s for sensitive sites |
| `AUTOTHROTTLE_ENABLED` | Adapts delay to server latency | **On.** Start at 1 s, target concurrency 2 to 4 |
| `RETRY_TIMES` / `RETRY_HTTP_CODES` | Retry transient failures | 2 to 3, include 429 and 5xx |
| `DOWNLOAD_TIMEOUT` | Give up on a hanging request | 20 to 30 s (default is 180, too long) |
| `ROBOTSTXT_OBEY` | Respect robots.txt | **On**, unless you have permission to ignore it |

## Browser or not?

| Option | Use when | Cost |
|---|---|---|
| Plain Scrapy | Data is in the HTML or in a JSON call | Cheapest. Thousands of pages per minute |
| Scrapy + `scrapy-playwright` | A few pages need JavaScript, the rest are plain | Browser only on flagged requests, concurrency must stay low |
| Selenium/Playwright **to log in**, Scrapy for the bulk | The login or token step is the hard part | Browser once per session, then cookies go to Scrapy |
| Full browser for everything | Heavy anti-bot, the whole site is JS-driven | Slowest, most memory. Last resort |

The **login-then-hand-off** pattern is often the best answer to "must have Selenium" in a Scrapy job: let the browser do the one thing only it can, then let Scrapy do the volume.

## Storage

| Option | Use when |
|---|---|
| PostgreSQL | Structured, relational, you query and join it, you need upserts and constraints (default choice) |
| MongoDB | Records have uneven shapes, or you store raw documents beside parsed fields |
| JSON Lines file (`FEEDS`) | Debugging, handoffs, backups of raw output |
| S3/object storage | Raw HTML or PDFs kept as evidence (see the migration guide) |

Whatever you choose, **write idempotently**: a unique key and an upsert, so reruns and backfills never create duplicates.

## Running and scheduling

| Option | Use when |
|---|---|
| `cron` + `scripts/run_spider.py` | One machine, a handful of spiders |
| Scrapyd | Several spiders, you want an HTTP API to start and stop jobs |
| Airflow / Prefect / Dagster | Dependencies between jobs, retries, backfills by date, alerting |
| Docker + Kubernetes CronJob | You already run on Kubernetes |

Pick the smallest tool that gives you retries, logs and an alert when a run fails or comes back short.

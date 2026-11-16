# Core concepts

## The request lifecycle

```
          ┌────────────────────────── Engine ──────────────────────────┐
          │                                                             │
 Spider ──┼─ start requests ─▶ Scheduler ─▶ Downloader middlewares ─▶ Downloader ─▶ website
   ▲      │   (queue + dedupe)            (process_request)                            │
   │      │                                                                            │
   │      │◀─ Items ◀── Spider middlewares ◀── callback(response) ◀── Downloader middlewares
   │      │       │                                                 (process_response)
   │      │       ▼
   │      │  Item pipelines (validate ─▶ dedupe ─▶ store)
   └──────┴─ new Requests go back to the Scheduler
```

Everything runs on one thread with an event loop (Twisted, using asyncio by default). That is why Scrapy handles thousands of concurrent requests cheaply, and why **blocking code is the enemy** (see the gotchas guide).

| Piece | Job | You write it when |
|---|---|---|
| Spider | Says where to start, how to parse a response, which links to follow | Always. One per source |
| Scheduler | Queues requests and drops duplicates (request fingerprint) | Almost never; configure it |
| Downloader | Sends HTTP, enforces concurrency and delays | Never; configure it |
| Downloader middleware | Hooks around every request/response: headers, proxies, retries, soft-block detection | Cross-cutting request behaviour |
| Spider middleware | Hooks around callback input/output | Rare |
| Item | The typed record a spider yields | Always |
| ItemLoader | Cleans raw values (strip, type-convert) before the item is built | When the same cleaning repeats |
| Item pipeline | Validate, dedupe, enrich, store each item | Always, for anything beyond a demo |
| Extension | Hooks on signals (spider opened/closed, item scraped): monitoring, guards | Monitoring and guard rails |
| Settings | Configuration: concurrency, delays, middlewares, pipelines, feeds | Always |

## The spider

```python
class BooksSpider(scrapy.Spider):
    name = "books"
    start_urls = ["https://books.toscrape.com/"]

    def parse(self, response):
        for href in response.css("article.product_pod h3 a::attr(href)").getall():
            yield response.follow(href, callback=self.parse_book)
        yield from response.follow_all(response.css("li.next a"), callback=self.parse)
```

Three rules:

1. A callback **yields** items (data) and requests (more work). Never `return` a list of mixed things.
2. `response.follow` handles relative URLs for you. `scrapy.Request` does not.
3. State you need in the next callback goes in `cb_kwargs` (preferred) or `meta`. Do not use lambdas as callbacks if you want to pause and resume with `JOBDIR`, because lambdas cannot be serialised.

## Selectors

```python
response.css("div.price::text").get()          # first match or None
response.css("div.price::text").getall()       # list
response.xpath("//a[@class='next']/@href").get()
product.css("h3 a::attr(title)").get()         # relative to a previous selector
product.xpath(".//span")                       # NOTE the dot
```

Gotchas: `//` inside a selected element searches the **whole document**, `.//` searches inside the element. `::text` returns only direct text nodes; use XPath `string(.)` if text is split across tags. `.get()` returns `None` on no match, so validate.

## Items and loaders

Use a dataclass (typed, readable, works with `itemadapter`):

```python
@dataclass
class BookItem:
    url: str
    title: str
    price_gbp: Decimal | None = None
```

Use an `ItemLoader` when you clean the same way in many places (strip, parse price, join text). Use plain assignment when each field is one line. The loader is for **cleaning**; the pipeline is for **validating**. Keep the two apart so a bad value is caught by a rule you can test.

## Pipelines

`process_item(item)` runs once per item, in order of the number in `ITEM_PIPELINES` (lower first). Return the item to continue, or `raise DropItem(...)` to stop. Typical order here: **validate (100), dedupe (200), store (300)**. Validate first so you never store junk and never waste a database write on it.

## Settings precedence (highest wins)

1. Command line: `-s DOWNLOAD_DELAY=2`
2. Spider `custom_settings`
3. Project `settings.py`
4. Scrapy defaults

Spider arguments (`-a start_date=2026-01-01`) are strings. Convert them yourself.

## The debugging toolbox

```bash
scrapy shell "https://books.toscrape.com/"     # interactive, try selectors live
scrapy fetch --nolog URL > page.html           # save a page for a fixture
scrapy parse --spider=books -c parse_book URL  # run one callback and print the result
scrapy check books                             # run contracts in docstrings
scrapy list                                    # list spiders
```

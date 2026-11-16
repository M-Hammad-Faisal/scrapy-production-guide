# Bot protection and browsers

This is where your existing experience (Playwright, Patchright, CAPTCHA handling, rotation systems) carries straight over. Scrapy gives you a fast HTTP client; it does not give you a browser. The question is always: **how little browser can I get away with?**

Use these techniques only on sources you are allowed to access. For public data, check for an official API or bulk download first; it is usually more reliable, faster and clearly legitimate.

## The layers a site can use

| Layer | What the site sees | What helps |
|---|---|---|
| Rate and IP reputation | Too many requests from one address, datacentre IPs | AutoThrottle, lower concurrency, rotating proxies |
| Headers and cookies | Missing or odd `User-Agent`, `Accept-Language`, no cookies | Realistic headers, a session cookie jar |
| TLS and HTTP fingerprint | The TLS handshake of Twisted does not look like Chrome | A different download handler that imitates a browser (for example the `scrapy-impersonate` / `curl_cffi` approach; check it is maintained before relying on it) |
| JavaScript challenge | A script must run before content appears | A real browser for that request |
| CAPTCHA | A human test | A solving service, or avoid by being gentle and using a warm session |
| Behavioural analysis | Mouse movement, timing, scroll | A browser with human-like pacing (for example Patchright) |

Scrapy alone covers the first two. Past that, you add pieces.

## Escalation ladder

1. **Official API / bulk file.** Done. No bot problem.
2. **The JSON call behind the page.** Open DevTools, Network tab, filter XHR, find the request that returns the data, copy it as cURL. Replicate it in a spider. (`quotes_api` shows this.)
3. **Plain HTML with polite settings.** AutoThrottle, a realistic UA pool, a retry policy.
4. **Proxies.** Rotate per request or per session. Sticky sessions matter for logins.
5. **Browser for the hard step only.** Log in or pass the challenge once, export the cookies, let Scrapy do the volume.
6. **Browser for every page.** Last resort. Budget memory and time.

## Soft blocks: HTTP 200 with a block page

The most expensive bug in scraping is not a 403. It is a 200 whose body says "access denied" or contains a CAPTCHA, which then flows through your parser and produces empty or garbage rows.

`SoftBlockMiddleware` (in `crawlers/middlewares.py`) looks for configurable markers in the body, retries with a limit (`get_retry_request`), and counts blocks in the stats so you can alert on them.

## Selenium inside a Scrapy project

If the team says "Selenium is a must have", three honest patterns exist:

| Pattern | How | Trade-off |
|---|---|---|
| **Login, then hand off** | Selenium logs in, you read `driver.get_cookies()`, put them into `Request(cookies=...)` | Best throughput. Needs cookie refresh logic |
| **Downloader middleware renders** | Middleware calls Selenium for flagged requests and returns an `HtmlResponse` | Simple, but it **blocks the reactor**, so wrap it in `deferToThread` and keep concurrency low |
| **Separate renderer service** | A small service (Selenium Grid / Playwright) behind an HTTP call | Isolates the browser, scales on its own, more moving parts |

Note: the old `scrapy-selenium` package has not been actively maintained for years. Most teams write a small middleware of their own or use `scrapy-playwright`.

## scrapy-playwright in practice

Settings (see `quotes_js.py` `custom_settings`):

```python
DOWNLOAD_HANDLERS = {
    "http":  "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
```

Per request: `meta={"playwright": True}`. Gotchas: keep `CONCURRENT_REQUESTS` small, close pages you open with `playwright_include_page`, wait for a selector instead of a fixed sleep, and install the browsers (`playwright install chromium`).

## What not to do

- Do not rotate user agents randomly and call it done. A Chrome UA with a non-Chrome TLS fingerprint and no cookies is a stronger signal than a plain honest UA.
- Do not retry a blocked request instantly at full speed. You teach the site to ban you.
- Do not hide credentials or proxy URLs in code.
- Do not scrape personal data or ignore terms of use because it is technically possible.

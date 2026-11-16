"""Project settings. Every non-default value has a reason, written next to it.

Precedence (highest wins): command line -s > spider custom_settings > this file > Scrapy defaults.
Secrets and environment-specific values come from environment variables (see .env.example).
"""

import os

try:  # optional: load a local .env in development
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _env_list(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


BOT_NAME = "crawlers"
SPIDER_MODULES = ["crawlers.spiders"]
NEWSPIDER_MODULE = "crawlers.spiders"

# --- Identity and politeness -------------------------------------------------------------------
# Be honest by default: say who you are and how to reach you. Change the contact URL.
USER_AGENT = os.getenv(
    "USER_AGENT", "scrapy-production-guide/0.1 (+https://github.com/M-Hammad-Faisal/scrapy-production-guide)"
)
# Respect robots.txt. Only turn this off with permission, per spider, and write down why.
ROBOTSTXT_OBEY = True

# --- Concurrency and throttling ----------------------------------------------------------------
CONCURRENT_REQUESTS = 8  # global; the default (16) is fine for many sites, lower is kinder
CONCURRENT_REQUESTS_PER_DOMAIN = 4  # the number that actually protects one site
DOWNLOAD_DELAY = 0.25  # a floor under AutoThrottle
# AutoThrottle adapts the delay to the server's latency. Leave it on in production.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0  # average parallel requests per remote server

# --- Failure handling --------------------------------------------------------------------------
DOWNLOAD_TIMEOUT = 20  # the default is 180 s, far too long: hung requests pile up
RETRY_ENABLED = True
RETRY_TIMES = 2  # retries multiply traffic (3 tries = 3x load on a failing site)
RETRY_HTTP_CODES = [408, 429, 500, 502, 503, 504, 522, 524]
# Soft blocks (HTTP 200 with a block page): see middlewares.SoftBlockMiddleware
SOFT_BLOCK_MARKERS = ["verify you are human", "access denied", "captcha", "unusual traffic"]
SOFT_BLOCK_MAX_RETRIES = 2

# --- Components --------------------------------------------------------------------------------
DOWNLOADER_MIDDLEWARES = {
    "crawlers.middlewares.RotatingUserAgentMiddleware": 450,
    "crawlers.middlewares.ProxyMiddleware": 460,
    "crawlers.middlewares.SoftBlockMiddleware": 560,
}
# Optional, from the environment. Empty means the middleware disables itself (NotConfigured).
USER_AGENT_POOL = _env_list("USER_AGENT_POOL")
PROXY_URLS = _env_list("PROXY_URLS")

ITEM_PIPELINES = {
    "crawlers.pipelines.ValidationPipeline": 100,  # reject bad items first, count by rule
    "crawlers.pipelines.DedupePipeline": 200,  # cheap in-run dedupe
    "crawlers.pipelines.StoragePipeline": 300,  # batched idempotent upsert (SQL)
    "crawlers.mongo_pipeline.MongoPipeline": 310,  # optional second sink; off unless MONGODB_URI
}
EXTENSIONS = {
    "crawlers.extensions.GuardExtension": 500,
}
# Guard thresholds. Override per spider with custom_settings.
MIN_ITEMS = 1  # a run that returns nothing must fail, not "succeed"
MAX_DROP_RATIO = 0.2  # more than 20% rejected items means the selectors probably rotted

# --- Storage -----------------------------------------------------------------------------------
# SQLite by default (zero setup). For PostgreSQL:
#   DATABASE_URL=postgresql+psycopg://crawler:crawler@localhost:5432/crawl
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/crawl.db")
STORAGE_BATCH_SIZE = 100
# Optional MongoDB sink (docker compose up -d mongo):
#   MONGODB_URI=mongodb://localhost:27017
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "crawl")

# Raw output as JSON Lines: great for debugging and backups. Use JSON Lines, not a single JSON
# array: if the process dies, an array file is invalid, while JSON Lines keeps every finished line.
FEEDS = {
    "data/raw/%(name)s/%(time)s.jsonl": {
        "format": "jsonlines",
        "encoding": "utf-8",
        "mode": "append",  # the file name has a timestamp, so each run gets its own file
    }
}

# Stats prefixes that make `scripts/run_spider.py` fail the run. A scheduler only sees the exit
# code, so everything that means "data may be missing or wrong" must be listed here.
FAIL_ON_STATS = [
    "errback/",  # a request failed for good (404 after retries, timeout, DNS ...)
    "soft_block/gave_up",  # blocked and retries exhausted
    "iso/incomplete_day",  # a day with the wrong number of intervals
    "iso/bad_interval",  # an interval that cannot exist (daylight-saving gap) or is malformed
]

# --- Runtime and safety ------------------------------------------------------------------------
# Required by scrapy-playwright and by StoragePipeline's asyncio.to_thread.
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG logs headers, which can include secrets
TELNETCONSOLE_ENABLED = False  # the telnet console is a remote shell into your process
MEMUSAGE_ENABLED = True
MEMUSAGE_LIMIT_MB = 1024  # stop a runaway crawl before the OS kills the whole machine
# Pause/resume: set JOBDIR=jobs/books-2026-03 to persist the queue and seen-set on disk.
# Do not share a JOBDIR between different runs or code versions.
if os.getenv("JOBDIR"):
    JOBDIR = os.environ["JOBDIR"]

# --- Development helpers (OFF in production) ---------------------------------------------------
# The HTTP cache replays saved responses: perfect while writing selectors, dangerous in
# production because you would parse stale pages.
HTTPCACHE_ENABLED = _env_bool("HTTPCACHE_ENABLED", False)
HTTPCACHE_DIR = ".scrapy/httpcache"
HTTPCACHE_EXPIRATION_SECS = 0

# --- Mock ISO feed used by the iso_prices spider ----------------------------------------------
ISO_BASE_URL = os.getenv("ISO_BASE_URL", "http://127.0.0.1:8765")

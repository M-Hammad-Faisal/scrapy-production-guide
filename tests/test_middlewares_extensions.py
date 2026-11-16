import importlib.util
from pathlib import Path

import pytest
from scrapy import Request
from scrapy.exceptions import IgnoreRequest, NotConfigured
from scrapy.http import HtmlResponse

from crawlers.extensions import GuardExtension
from crawlers.middlewares import (
    ProxyMiddleware,
    RotatingUserAgentMiddleware,
    SoftBlockMiddleware,
)

URL = "https://example.com/data"


def html(body: str, status: int = 200, request: Request | None = None) -> HtmlResponse:
    return HtmlResponse(URL, status=status, body=body.encode(), encoding="utf-8", request=request)


class TestSoftBlock:
    def middleware(self, make_crawler, retries=2):
        crawler, _ = make_crawler(
            {"SOFT_BLOCK_MARKERS": ["verify you are human"], "SOFT_BLOCK_MAX_RETRIES": retries}
        )
        return SoftBlockMiddleware.from_crawler(crawler), crawler

    def test_normal_page_passes_through(self, make_crawler):
        mw, _ = self.middleware(make_crawler)
        response = html("<p>real data</p>")
        assert mw.process_response(Request(URL), response) is response

    def test_block_page_with_status_200_is_retried(self, make_crawler):
        mw, crawler = self.middleware(make_crawler)
        result = mw.process_response(Request(URL), html("<h1>Please VERIFY you are human</h1>"))
        assert isinstance(result, Request)  # a retry, not the poisoned response
        assert result.meta["retry_times"] == 1
        assert crawler.stats.get_value("soft_block/detected") == 1

    def test_gives_up_after_the_limit_instead_of_looping(self, make_crawler):
        mw, crawler = self.middleware(make_crawler, retries=1)
        request = Request(URL, meta={"retry_times": 1})  # already used its one retry
        with pytest.raises(IgnoreRequest):
            mw.process_response(request, html("verify you are human"))
        assert crawler.stats.get_value("soft_block/gave_up") == 1

    def test_non_200_is_left_to_the_retry_middleware(self, make_crawler):
        mw, _ = self.middleware(make_crawler)
        response = html("verify you are human", status=503)
        assert mw.process_response(Request(URL), response) is response

    def test_disabled_when_no_markers(self, make_crawler):
        crawler, _ = make_crawler({"SOFT_BLOCK_MARKERS": []})
        with pytest.raises(NotConfigured):
            SoftBlockMiddleware.from_crawler(crawler)


class TestUserAgentAndProxy:
    def test_ua_pool_sets_a_header_but_never_overrides_one(self):
        mw = RotatingUserAgentMiddleware(["UA-1", "UA-2"], seed=1)
        req = Request(URL)
        mw.process_request(req)
        assert req.headers["User-Agent"].decode() in {"UA-1", "UA-2"}
        fixed = Request(URL, headers={"User-Agent": "custom"})
        mw.process_request(fixed)
        assert fixed.headers["User-Agent"] == b"custom"

    def test_proxies_rotate_and_can_be_bypassed(self):
        mw = ProxyMiddleware(["http://p1:8080", "http://p2:8080"])
        seen = []
        for _ in range(3):
            req = Request(URL)
            mw.process_request(req)
            seen.append(req.meta["proxy"])
        assert seen == ["http://p1:8080", "http://p2:8080", "http://p1:8080"]
        bypass = Request(URL, meta={"no_proxy": True})
        mw.process_request(bypass)
        assert "proxy" not in bypass.meta

    def test_both_disable_themselves_when_unconfigured(self, make_crawler):
        crawler, _ = make_crawler({"USER_AGENT_POOL": [], "PROXY_URLS": []})
        with pytest.raises(NotConfigured):
            RotatingUserAgentMiddleware.from_crawler(crawler)
        with pytest.raises(NotConfigured):
            ProxyMiddleware.from_crawler(crawler)


class TestGuardExtension:
    def close(self, make_crawler, settings, scraped, dropped):
        crawler, spider = make_crawler(settings)
        crawler.stats.set_value("item_scraped_count", scraped)
        crawler.stats.set_value("item_dropped_count", dropped)
        GuardExtension.from_crawler(crawler).spider_closed(spider, "finished")
        return crawler.stats

    def test_zero_items_fails_the_run(self, make_crawler):
        stats = self.close(make_crawler, {"MIN_ITEMS": 5}, scraped=0, dropped=0)
        assert stats.get_value("guard/failed") is True
        assert "expected at least 5" in stats.get_value("guard/reasons")

    def test_high_drop_ratio_fails_the_run(self, make_crawler):
        stats = self.close(make_crawler, {"MAX_DROP_RATIO": 0.2}, scraped=7, dropped=3)
        assert stats.get_value("guard/failed") is True  # 30% dropped

    def test_healthy_run_passes(self, make_crawler):
        stats = self.close(make_crawler, {"MIN_ITEMS": 5, "MAX_DROP_RATIO": 0.2}, 95, 5)
        assert stats.get_value("guard/failed") is False

    def test_disabled_without_thresholds(self, make_crawler):
        crawler, _ = make_crawler({"MIN_ITEMS": 0, "MAX_DROP_RATIO": 0})
        with pytest.raises(NotConfigured):
            GuardExtension.from_crawler(crawler)


def load_runner():
    path = Path(__file__).parent.parent / "scripts" / "run_spider.py"
    spec = importlib.util.spec_from_file_location("run_spider", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRunnerVerdict:
    """The wrapper must catch what `scrapy crawl` exit code 0 hides."""

    def test_healthy(self):
        stats = {"finish_reason": "finished", "item_scraped_count": 10}
        assert load_runner().evaluate(stats, max_errors=0) == []

    def test_guard_failure_callback_exceptions_and_errors_are_reported(self):
        stats = {
            "finish_reason": "finished",
            "guard/failed": True,
            "guard/reasons": "only 0 items",
            "log_count/ERROR": 3,
            "spider_exceptions/KeyError": 2,
        }
        problems = load_runner().evaluate(stats, max_errors=0)
        assert len(problems) == 3

    def test_gap_stats_fail_the_run_even_when_the_crawl_itself_finished(self):
        # A 404 for one day's file or a day with a missing hour is a DATA problem. Without
        # FAIL_ON_STATS the run would report success while data is missing.
        stats = {"finish_reason": "finished", "errback/http_404": 1, "iso/incomplete_day": 2}
        problems = load_runner().evaluate(
            stats, max_errors=0, fail_on=["errback/", "iso/incomplete_day"]
        )
        assert len(problems) == 2

    def test_abnormal_finish_reason_fails(self):
        problems = load_runner().evaluate({"finish_reason": "shutdown"}, max_errors=0)
        assert problems == ["finish_reason=shutdown"]

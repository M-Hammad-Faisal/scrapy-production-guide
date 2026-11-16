"""The manual-entry API: same validation, same upsert, provenance, and 'manual wins'."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from django.test import override_settings
from rest_framework.test import APIClient

from crawlers import storage
from crawlers.items import PriceItem
from manual_entry import db

T0 = "2026-06-15T04:00:00Z"
T0_DT = datetime(2026, 6, 15, 4, tzinfo=UTC)


@pytest.fixture
def api(tmp_path):
    url = f"sqlite:///{tmp_path}/api.db"
    with override_settings(
        MANUAL_ENTRY_DATABASE_URL=url, MANUAL_ENTRY_KEYS="alice:key-a,bob:key-b"
    ):
        client = APIClient()
        client.url = url  # handy for assertions
        yield client
    db._engines.pop(url, None)


def entry(**kw):
    base = {
        "source": "mockiso", "node": "HUB_A", "interval_start_utc": T0,
        "price_usd_mwh": "41.2500", "reason": "settlement correction, ticket 4812",
    }
    return {**base, **kw}


def rows(api):
    engine = sa.create_engine(api.url)
    storage.create_all(engine)  # a rejected request never touches the DB, so ensure the schema
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sa.select(storage.iso_prices))]


def post_manual(api, **kw):
    return api.post("/api/prices/", entry(**kw), format="json", HTTP_X_API_KEY="key-a")


def scraped_item(price="30.0000"):
    return PriceItem(
        source="mockiso", node="HUB_A", interval_start_utc=T0_DT, interval_minutes=60,
        price_usd_mwh=Decimal(price), local_label="2026-06-15 HE1",
    )


class TestAuth:
    def test_requests_without_a_key_are_rejected(self, api):
        assert api.post("/api/prices/", entry(), format="json").status_code == 401

    def test_wrong_key_is_rejected(self, api):
        resp = api.post("/api/prices/", entry(), format="json", HTTP_X_API_KEY="nope")
        assert resp.status_code == 401

    def test_no_configured_keys_means_nobody_gets_in(self, api):
        with override_settings(MANUAL_ENTRY_KEYS=""):
            resp = api.post("/api/prices/", entry(), format="json", HTTP_X_API_KEY="anything")
        assert resp.status_code == 401


class TestEntering:
    def post(self, api, payload, key="key-a", path="/api/prices/"):
        return api.post(path, payload, format="json", HTTP_X_API_KEY=key)

    def test_valid_entry_is_stored_with_provenance(self, api):
        resp = self.post(api, entry())
        assert resp.status_code == 201 and resp.json()["entered_by"] == "alice"
        (row,) = rows(api)
        assert (row["origin"], row["entered_by"]) == ("manual", "alice")
        assert row["reason"] == "settlement correction, ticket 4812"
        assert Decimal(str(row["price_usd_mwh"])) == Decimal("41.2500")

    def test_entered_by_comes_from_the_key_never_from_the_body(self, api):
        self.post(api, entry(entered_by="the-ceo", origin="scraped"), key="key-b")
        (row,) = rows(api)
        assert (row["entered_by"], row["origin"]) == ("bob", "manual")

    def test_naive_timestamp_is_refused_not_silently_assumed_utc(self, api):
        resp = self.post(api, entry(interval_start_utc="2026-06-15T04:00:00"))
        assert resp.status_code == 400
        assert "explicit UTC offset" in str(resp.json())
        assert rows(api) == []

    def test_offset_timestamps_are_converted_to_utc(self, api):
        self.post(api, entry(interval_start_utc="2026-06-15T00:00:00-04:00"))
        (row,) = rows(api)
        assert row["interval_start_utc"].replace(tzinfo=UTC) == T0_DT

    def test_scraper_rules_apply_to_manual_entries_too(self, api):
        resp = self.post(api, entry(price_usd_mwh="99999"))
        assert resp.status_code == 400
        assert resp.json()["errors"][0]["rule"] == "price_sane"

    def test_a_reason_is_mandatory(self, api):
        resp = self.post(api, entry(reason="x"))
        assert resp.status_code == 400
        assert resp.json()["errors"][0]["rule"] == "manual_needs_reason"

    def test_negative_prices_are_legal(self, api):
        assert self.post(api, entry(price_usd_mwh="-8.40")).status_code == 201

    def test_bulk_is_all_or_nothing(self, api):
        good = entry(node="HUB_A")
        bad = entry(node="ZONE_B", price_usd_mwh="99999")
        resp = self.post(api, [good, bad], path="/api/prices/bulk/")
        assert resp.status_code == 400
        assert rows(api) == []  # the good row was NOT written either

    def test_bulk_success_and_rerun_is_idempotent(self, api):
        payload = [entry(node="HUB_A"), entry(node="ZONE_B")]
        for _ in range(2):
            assert self.post(api, payload, path="/api/prices/bulk/").status_code == 201
        assert len(rows(api)) == 2


class TestManualWins:
    def test_a_later_crawl_does_not_overwrite_a_manual_value(self, api):
        post_manual(api, price_usd_mwh="41.25")
        engine = sa.create_engine(api.url)
        result = storage.write_batch(engine, [scraped_item("30.0")])  # the nightly scrape
        assert (result.written, result.skipped) == (0, 1)
        (row,) = rows(api)
        assert Decimal(str(row["price_usd_mwh"])) == Decimal("41.25") and row["origin"] == "manual"

    def test_a_manual_entry_does_overwrite_a_scraped_value(self, api):
        engine = sa.create_engine(api.url)
        storage.create_all(engine)
        storage.write_batch(engine, [scraped_item("30.0")])
        post_manual(api, price_usd_mwh="41.25")
        (row,) = rows(api)
        assert (row["origin"], Decimal(str(row["price_usd_mwh"]))) == ("manual", Decimal("41.25"))

    def test_scraped_rows_are_still_refreshed_by_the_crawl(self, api):
        engine = sa.create_engine(api.url)
        storage.create_all(engine)
        storage.write_batch(engine, [scraped_item("30.0")])
        result = storage.write_batch(engine, [scraped_item("31.5")])  # a revision from the source
        assert (result.written, result.skipped) == (1, 0)

    def test_listing_shows_provenance_and_filters_by_origin(self, api):
        engine = sa.create_engine(api.url)
        storage.create_all(engine)
        storage.write_batch(engine, [scraped_item("30.0")])
        api.post(
            "/api/prices/", entry(node="ZONE_B"), format="json", HTTP_X_API_KEY="key-a"
        )
        body = api.get("/api/prices/?origin=manual", HTTP_X_API_KEY="key-a").json()
        assert body["count"] == 1
        assert body["results"][0]["entered_by"] == "alice"
        assert api.get("/api/prices/", HTTP_X_API_KEY="key-a").json()["count"] == 2

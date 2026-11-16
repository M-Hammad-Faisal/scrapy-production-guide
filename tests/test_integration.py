"""Tests against REAL PostgreSQL and MongoDB servers. Skipped unless these are set:

    INTEGRATION_POSTGRES_URL=postgresql+psycopg://crawler:crawler@localhost:5432/crawl_test
    INTEGRATION_MONGO_URI=mongodb://localhost:27017

``make test-integration`` starts the containers, sets the variables and runs these.

Why bother, when SQLite and unit tests exist? Because the behaviours that matter most differ per
engine: how ON CONFLICT ... WHERE counts skipped rows, what a duplicate key inside one batch does,
how Mongo reports a filtered upsert that hits a unique index. Mocks cannot prove those.
"""

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa

from crawlers import storage
from crawlers.items import PriceItem

PG_URL = os.getenv("INTEGRATION_POSTGRES_URL")
MONGO_URI = os.getenv("INTEGRATION_MONGO_URI")
T0 = datetime(2026, 6, 15, 4, tzinfo=UTC)

pytestmark = pytest.mark.integration


def item(value="30.0", origin="scraped", node="HUB_A"):
    manual = origin == "manual"
    return PriceItem(
        source="mockiso", node=node, interval_start_utc=T0, interval_minutes=60,
        price_usd_mwh=Decimal(value), local_label="x", origin=origin,
        entered_by="alice" if manual else None, reason="correction ticket 1" if manual else None,
    )


@pytest.mark.skipif(not PG_URL, reason="INTEGRATION_POSTGRES_URL not set")
class TestPostgres:
    @pytest.fixture
    def engine(self):
        assert sa.engine.make_url(PG_URL).database.endswith("_test"), "refusing: not a *_test DB"
        engine = sa.create_engine(PG_URL)
        storage.metadata.drop_all(engine)  # create_all never migrates, so start from scratch
        storage.create_all(engine)
        yield engine
        engine.dispose()

    def read(self, engine):
        with engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(sa.select(storage.iso_prices))]

    def test_same_key_twice_in_one_batch_does_not_crash(self, engine):
        # PostgreSQL: "ON CONFLICT DO UPDATE command cannot affect row a second time"
        result = storage.write_batch(engine, [item("1"), item("2")])
        assert result.written == 1
        assert Decimal(str(self.read(engine)[0]["price_usd_mwh"])) == Decimal("2")

    def test_rerun_is_idempotent(self, engine):
        for _ in range(3):
            storage.write_batch(engine, [item(node="HUB_A"), item(node="ZONE_B")])
        assert len(self.read(engine)) == 2

    def test_manual_value_survives_a_crawl_and_the_skip_is_counted(self, engine):
        storage.write_batch(engine, [item("30")])
        storage.write_batch(engine, [item("41.25", origin="manual")], manual=True)
        crawl = storage.write_batch(engine, [item("31")])  # the nightly scrape
        assert (crawl.written, crawl.skipped) == (0, 1)  # rowcount semantics on PostgreSQL
        (row,) = self.read(engine)
        assert (row["origin"], Decimal(str(row["price_usd_mwh"]))) == ("manual", Decimal("41.25"))

    def test_scraped_rows_are_still_revised_by_a_crawl(self, engine):
        storage.write_batch(engine, [item("30")])
        crawl = storage.write_batch(engine, [item("31.5")])
        assert (crawl.written, crawl.skipped) == (1, 0)

    def test_timestamps_round_trip_as_timezone_aware_utc(self, engine):
        storage.write_batch(engine, [item()])
        stored = self.read(engine)[0]["interval_start_utc"]
        assert stored.utcoffset().total_seconds() == 0 and stored == T0


@pytest.mark.skipif(not MONGO_URI, reason="INTEGRATION_MONGO_URI not set")
class TestMongo:
    @pytest.fixture
    def db(self):
        from pymongo import MongoClient

        from crawlers import mongo_pipeline

        client = MongoClient(MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=3000)
        client.drop_database("crawl_test")
        database = client["crawl_test"]
        mongo_pipeline.ensure_indexes(database)
        yield database
        client.drop_database("crawl_test")
        client.close()

    def test_rerun_is_idempotent(self, db):
        from crawlers import mongo_pipeline

        for _ in range(3):
            mongo_pipeline.write_batch(db, [item(node="HUB_A"), item(node="ZONE_B")])
        assert db.iso_prices.count_documents({}) == 2

    def test_decimal_and_timezone_round_trip(self, db):
        from bson.decimal128 import Decimal128

        from crawlers import mongo_pipeline

        mongo_pipeline.write_batch(db, [item("40.5")])
        doc = db.iso_prices.find_one()
        assert isinstance(doc["price_usd_mwh"], Decimal128)
        assert doc["price_usd_mwh"].to_decimal() == Decimal("40.5")
        assert doc["interval_start_utc"] == T0 and doc["interval_start_utc"].tzinfo is not None

    def test_manual_value_survives_a_crawl_and_duplicate_key_is_counted_as_skipped(self, db):
        from crawlers import mongo_pipeline

        mongo_pipeline.write_batch(db, [item("41.25", origin="manual")], manual=True)
        crawl = mongo_pipeline.write_batch(db, [item("31")])  # E11000 under the hood
        assert (crawl.written, crawl.skipped) == (0, 1)
        assert db.iso_prices.count_documents({}) == 1
        assert db.iso_prices.find_one()["origin"] == "manual"

    def test_manual_entry_overwrites_a_scraped_value(self, db):
        from crawlers import mongo_pipeline

        mongo_pipeline.write_batch(db, [item("30")])
        mongo_pipeline.write_batch(db, [item("41.25", origin="manual")], manual=True)
        doc = db.iso_prices.find_one()
        assert (doc["origin"], doc["price_usd_mwh"].to_decimal()) == ("manual", Decimal("41.25"))

    def test_one_conflict_does_not_abort_the_rest_of_the_batch(self, db):
        from crawlers import mongo_pipeline

        mongo_pipeline.write_batch(db, [item("1", origin="manual", node="HUB_A")], manual=True)
        crawl = mongo_pipeline.write_batch(db, [item("2", node="HUB_A"), item("3", node="ZONE_B")])
        assert (crawl.written, crawl.skipped) == (1, 1)  # ordered=False: ZONE_B still written
        assert db.iso_prices.count_documents({}) == 2

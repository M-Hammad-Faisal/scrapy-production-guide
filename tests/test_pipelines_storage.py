import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from scrapy.exceptions import DropItem
from sqlalchemy.dialects import postgresql

from crawlers import storage
from crawlers.items import BookItem, PriceItem, QuoteItem
from crawlers.pipelines import DedupePipeline, StoragePipeline, ValidationPipeline

T0 = datetime(2026, 6, 15, 4, tzinfo=UTC)


def book(**kw):
    base = dict(url="https://b/1", title="T", price_gbp=Decimal("9.99"), rating=3)
    return BookItem(**{**base, **kw})


def price(**kw):
    base = dict(
        source="mockiso", node="HUB_A", interval_start_utc=T0, interval_minutes=60,
        price_usd_mwh=Decimal("40"), local_label="x",
    )
    return PriceItem(**{**base, **kw})


class TestValidation:
    def setup_method(self):
        pass

    def pipeline(self, make_crawler):
        crawler, _ = make_crawler()
        return ValidationPipeline.from_crawler(crawler), crawler

    def test_valid_items_pass_and_are_counted(self, make_crawler):
        pipe, crawler = self.pipeline(make_crawler)
        item = book()
        assert pipe.process_item(item) is item
        assert crawler.stats.get_value("validation/passed") == 1

    @pytest.mark.parametrize(
        ("item", "rule"),
        [
            (book(title=None), "title_required"),
            (book(price_gbp=None), "price_positive"),
            (book(price_gbp=Decimal("0")), "price_positive"),
            (book(rating=9), "rating_range"),
            (QuoteItem(text="", author="a"), "text_required"),
            (price(price_usd_mwh=None), "price_required"),
            (price(price_usd_mwh=Decimal("99999")), "price_sane"),
            (price(interval_start_utc=datetime(2026, 6, 15, 4)), "utc_timestamp"),
        ],
    )
    def test_each_rule_drops_and_counts_by_name(self, make_crawler, item, rule):
        pipe, crawler = self.pipeline(make_crawler)
        with pytest.raises(DropItem, match=rule):
            pipe.process_item(item)
        assert crawler.stats.get_value(f"validation/failed/{rule}") == 1

    def test_negative_market_price_is_valid(self, make_crawler):
        pipe, _ = self.pipeline(make_crawler)
        item = price(price_usd_mwh=Decimal("-8.40"))
        assert pipe.process_item(item) is item


class TestDedupe:
    def test_second_copy_in_same_run_is_dropped(self, make_crawler):
        crawler, _ = make_crawler()
        pipe = DedupePipeline.from_crawler(crawler)
        assert pipe.process_item(book()) is not None
        with pytest.raises(DropItem, match="duplicate"):
            pipe.process_item(book())
        assert crawler.stats.get_value("dedupe/dropped") == 1

    def test_different_utc_instants_do_not_collide(self, make_crawler):
        crawler, _ = make_crawler()
        pipe = DedupePipeline.from_crawler(crawler)
        pipe.process_item(price())
        pipe.process_item(price(interval_start_utc=datetime(2026, 6, 15, 5, tzinfo=UTC)))


class TestStorage:
    @pytest.fixture
    def engine(self, tmp_path):
        eng = sa.create_engine(f"sqlite:///{tmp_path}/t.db")
        storage.create_all(eng)
        return eng

    def count(self, engine, table):
        with engine.connect() as conn:
            return conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()

    def test_rerun_is_idempotent_and_revisions_overwrite(self, engine):
        storage.write_batch(engine, [price(), price(node="ZONE_B")])
        storage.write_batch(engine, [price(), price(node="ZONE_B")])  # exact rerun
        assert self.count(engine, storage.iso_prices) == 2  # no duplicates

        storage.write_batch(engine, [price(price_usd_mwh=Decimal("55.5"))])  # revised value
        with engine.connect() as conn:
            value = conn.execute(
                sa.select(storage.iso_prices.c.price_usd_mwh).where(
                    storage.iso_prices.c.node == "HUB_A"
                )
            ).scalar_one()
        assert Decimal(str(value)) == Decimal("55.5")
        assert self.count(engine, storage.iso_prices) == 2

    def test_duplicate_keys_inside_one_batch_do_not_crash(self, engine):
        # PostgreSQL would reject this multi-row upsert; write_batch collapses it first.
        written = storage.write_batch(engine, [book(title="old"), book(title="new")])
        assert written == 1
        with engine.connect() as conn:
            assert conn.execute(sa.select(storage.books.c.title)).scalar_one() == "new"

    def test_mixed_item_types_go_to_their_own_tables(self, engine):
        storage.write_batch(
            engine, [book(), QuoteItem(text="q", author="a", tags=["x", "y"]), price()]
        )
        assert self.count(engine, storage.books) == 1
        assert self.count(engine, storage.quotes) == 1
        assert self.count(engine, storage.iso_prices) == 1

    def test_postgres_upsert_statement_is_valid_sql(self):
        stmt = storage.upsert_statement(
            "postgresql", storage.iso_prices, ["source", "node", "interval_start_utc"],
            [{"source": "s", "node": "n", "interval_start_utc": T0, "interval_minutes": 60,
              "price_usd_mwh": Decimal("1"), "local_label": "x", "scraped_at": T0}],
        )
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT (source, node, interval_start_utc) DO UPDATE" in sql
        assert "price_usd_mwh = excluded.price_usd_mwh" in sql

    def test_pipeline_batches_and_flushes_the_tail_on_close(self, make_crawler, tmp_path):
        url = f"sqlite:///{tmp_path}/p.db"
        crawler, _ = make_crawler({"DATABASE_URL": url, "STORAGE_BATCH_SIZE": 3})
        pipe = StoragePipeline.from_crawler(crawler)

        async def run():
            pipe.open_spider()
            for i in range(7):  # 2 full batches of 3, plus a tail of 1
                await pipe.process_item(book(url=f"https://b/{i}"))
            assert crawler.stats.get_value("storage/batches") == 2
            await pipe.close_spider()  # must flush the tail

        asyncio.run(run())
        assert crawler.stats.get_value("storage/rows_written") == 7
        eng = sa.create_engine(url)
        assert self.count(eng, storage.books) == 7

    def test_sqlite_folder_is_created_on_a_fresh_checkout(self, make_crawler, tmp_path):
        # Regression: the first live run crashed with "unable to open database file".
        url = f"sqlite:///{tmp_path}/does/not/exist/yet/c.db"
        crawler, _ = make_crawler({"DATABASE_URL": url})
        pipe = StoragePipeline.from_crawler(crawler)
        pipe.open_spider()
        assert (tmp_path / "does/not/exist/yet/c.db").exists()

    def test_pipeline_disables_itself_without_database_url(self, make_crawler):
        from scrapy.exceptions import NotConfigured

        crawler, _ = make_crawler({"DATABASE_URL": ""})
        with pytest.raises(NotConfigured):
            StoragePipeline.from_crawler(crawler)

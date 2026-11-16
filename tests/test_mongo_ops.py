"""MongoDB logic that needs no server: document shape, grouping, and the manual guard."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128
from pymongo import ReplaceOne
from scrapy.exceptions import NotConfigured

from crawlers.items import BookItem, PriceItem
from crawlers.mongo_pipeline import (
    MongoPipeline,
    build_operations,
    to_document,
)

T0 = datetime(2026, 6, 15, 4, tzinfo=UTC)


def price(node="HUB_A", value="40.5"):
    return PriceItem(
        source="mockiso", node=node, interval_start_utc=T0, interval_minutes=60,
        price_usd_mwh=Decimal(value), local_label="x",
    )


def test_decimals_become_decimal128_never_float():
    doc = to_document(price())
    assert isinstance(doc["price_usd_mwh"], Decimal128)
    assert doc["price_usd_mwh"].to_decimal() == Decimal("40.5")


def test_none_values_stay_none():
    assert to_document(price(value="1"))["reason"] is None


def test_operations_group_by_collection_and_collapse_duplicate_keys():
    ops = build_operations(
        [
            price("HUB_A", "1"), price("HUB_A", "2"), price("ZONE_B", "3"),
            BookItem(url="u", title="t"),
        ]
    )
    assert sorted(ops) == ["books", "iso_prices"]
    assert len(ops["iso_prices"]) == 2  # the two HUB_A items collapsed, last wins
    assert all(isinstance(op, ReplaceOne) for op in ops["iso_prices"])


def test_scraped_writes_exclude_manual_rows_in_the_filter():
    (op,) = build_operations([price()])["iso_prices"]
    assert op._filter["origin"] == {"$ne": "manual"}
    assert op._upsert is True


def test_manual_writes_may_overwrite_anything():
    (op,) = build_operations([price()], manual=True)["iso_prices"]
    assert "origin" not in op._filter


def test_tables_without_provenance_have_no_origin_filter():
    (op,) = build_operations([BookItem(url="u", title="t")])["books"]
    assert op._filter == {"url": "u"}


def test_pipeline_disables_itself_without_a_uri(make_crawler):
    crawler, _ = make_crawler({"MONGODB_URI": ""})
    with pytest.raises(NotConfigured):
        MongoPipeline.from_crawler(crawler)

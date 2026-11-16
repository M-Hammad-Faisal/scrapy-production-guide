"""Database layer: table definitions and idempotent upserts.

SQLAlchemy Core is used so the same code runs on SQLite (zero setup, used in tests) and
PostgreSQL (production). The key idea: every table has a **natural unique key** and writes are
``INSERT ... ON CONFLICT DO UPDATE``. Rerunning a crawl or a backfill therefore never creates
duplicates, and a revised value overwrites the old one.
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

from crawlers.items import BookItem, PriceItem, QuoteItem

# SQLite has no native DECIMAL. SQLAlchemy warns once; PostgreSQL (production) is exact.
warnings.filterwarnings("ignore", message=".*does \\*not\\* support Decimal objects natively.*")

metadata = sa.MetaData()

books = sa.Table(
    "books",
    metadata,
    sa.Column("url", sa.Text, primary_key=True),
    sa.Column("upc", sa.Text),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("category", sa.Text),
    sa.Column("price_gbp", sa.Numeric(10, 2)),
    sa.Column("rating", sa.Integer),
    sa.Column("availability", sa.Integer),
    sa.Column("description", sa.Text),
    sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
)

quotes = sa.Table(
    "quotes",
    metadata,
    sa.Column("author", sa.Text, primary_key=True),
    sa.Column("text", sa.Text, primary_key=True),
    sa.Column("tags", sa.JSON),
    sa.Column("source_url", sa.Text),
    sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
)

iso_prices = sa.Table(
    "iso_prices",
    metadata,
    sa.Column("source", sa.Text, primary_key=True),
    sa.Column("node", sa.Text, primary_key=True),
    sa.Column("interval_start_utc", sa.DateTime(timezone=True), primary_key=True),
    sa.Column("interval_minutes", sa.Integer, nullable=False),
    sa.Column("price_usd_mwh", sa.Numeric(12, 4)),
    sa.Column("local_label", sa.Text),
    sa.Column("origin", sa.Text, nullable=False, server_default="scraped"),
    sa.Column("entered_by", sa.Text),
    sa.Column("reason", sa.Text),
    sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
)

# item class -> (table, columns that form the unique key)
TARGETS: dict[type, tuple[sa.Table, list[str]]] = {
    BookItem: (books, ["url"]),
    QuoteItem: (quotes, ["author", "text"]),
    PriceItem: (iso_prices, ["source", "node", "interval_start_utc"]),
}


def item_to_row(item: Any) -> tuple[sa.Table, list[str], dict[str, Any]]:
    table, key = TARGETS[type(item)]
    row = asdict(item)
    row["scraped_at"] = datetime.now(UTC)
    # Drop fields the table does not have (kept explicit so a typo cannot silently vanish).
    unknown = set(row) - set(table.c.keys())
    if unknown:
        raise KeyError(f"{type(item).__name__} has fields not in table {table.name}: {unknown}")
    return table, key, row


def upsert_statement(
    dialect_name: str,
    table: sa.Table,
    key: list[str],
    rows: list[dict],
    protect_manual: bool = False,
):
    """Build a dialect-specific ``INSERT ... ON CONFLICT DO UPDATE``.

    ``protect_manual=True`` adds ``WHERE origin <> 'manual'`` to the update: a scraper run may
    insert new rows and refresh scraped rows, but it must NEVER overwrite a value someone entered
    by hand. A conflicting row that fails the WHERE is skipped silently, which is why
    ``write_batch`` compares the affected row count with the number of rows it sent.
    """
    insert_fn = postgresql.insert if dialect_name == "postgresql" else sqlite.insert
    stmt = insert_fn(table).values(rows)
    update_cols = {c.name: stmt.excluded[c.name] for c in table.c if c.name not in key}
    where = table.c.origin != "manual" if protect_manual else None
    return stmt.on_conflict_do_update(index_elements=key, set_=update_cols, where=where)


@dataclass
class WriteResult:
    written: int  # rows inserted or updated
    skipped: int  # rows left alone because a manual value takes precedence


def write_batch(engine: sa.Engine, items: list[Any], *, manual: bool = False) -> WriteResult:
    """Write items, grouped by table, in one transaction.

    ``manual=True`` is for the manual-entry path: it may overwrite anything. The default
    (scraper) path will not overwrite rows whose ``origin`` is ``manual``.
    """
    # Gotcha: PostgreSQL refuses a multi-row upsert that contains the same key twice
    # ("cannot affect row a second time"). Collapse duplicates inside the batch, last one wins.
    grouped: dict[str, tuple[sa.Table, list[str], dict[tuple, dict]]] = {}
    for item in items:
        table, key, row = item_to_row(item)
        bucket = grouped.setdefault(table.name, (table, key, {}))[2]
        bucket[tuple(row[k] for k in key)] = row

    written = skipped = 0
    with engine.begin() as conn:
        for table, key, rows_by_key in grouped.values():
            rows = list(rows_by_key.values())
            protect = (not manual) and "origin" in table.c
            stmt = upsert_statement(engine.dialect.name, table, key, rows, protect_manual=protect)
            # Count with RETURNING, not rowcount. Found by the PostgreSQL integration test:
            # PostgreSQL itself reports "INSERT 0 0" for a skipped conflict, but SQLAlchemy
            # returns rowcount = -1 for this statement, so a rowcount-based counter silently
            # reported "everything written" and never noticed a protected manual value.
            # RETURNING yields one row per inserted/updated row and none for a skipped one,
            # on both PostgreSQL and SQLite.
            affected = len(conn.execute(stmt.returning(*[table.c[k] for k in key])).all())
            written += affected
            skipped += len(rows) - affected
    return WriteResult(written=written, skipped=skipped)


def create_all(engine: sa.Engine) -> None:
    metadata.create_all(engine)

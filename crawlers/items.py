"""Typed items. Use dataclasses: readable, typed, and supported by itemadapter.

Two styles are shown on purpose:

* ``BookItem`` / ``QuoteItem`` have defaults for every field, because ItemLoader instantiates the
  item empty and fills it in. Use this style with loaders.
* ``PriceItem`` has required fields and is built directly in the spider. Use this style when the
  spider already has clean, typed values and you want construction to fail loudly if one is
  missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class BookItem:
    url: str | None = None
    upc: str | None = None
    title: str | None = None
    category: str | None = None
    price_gbp: Decimal | None = None
    rating: int | None = None
    availability: int | None = None
    description: str | None = None


@dataclass
class QuoteItem:
    text: str | None = None
    author: str | None = None
    tags: list[str] = field(default_factory=list)
    source_url: str | None = None


@dataclass
class PriceItem:
    source: str
    node: str
    interval_start_utc: datetime
    interval_minutes: int
    price_usd_mwh: Decimal | None
    local_label: str  # the original text from the source, kept for audit

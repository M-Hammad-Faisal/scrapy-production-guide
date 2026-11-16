"""Small, pure parsing helpers.

Keep these free of Scrapy imports so they are trivial to unit-test.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_RATING_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def parse_price(raw: str | None) -> Decimal | None:
    """'£51.77' -> Decimal('51.77'). Returns None when no number is present.

    Uses Decimal, never float: money and prices must not accumulate binary rounding error.
    """
    if not raw:
        return None
    match = re.search(r"-?\d[\d,]*\.?\d*", raw)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def parse_rating(raw: str | None) -> int | None:
    """'star-rating Three' -> 3."""
    if not raw:
        return None
    for word in raw.lower().split():
        if word in _RATING_WORDS:
            return _RATING_WORDS[word]
    return None


def parse_availability(raw: str | None) -> int | None:
    """'In stock (22 available)' -> 22."""
    if not raw:
        return None
    match = re.search(r"\((\d+)\s+available\)", raw)
    return int(match.group(1)) if match else None


def clean_text(raw: str | None) -> str | None:
    """Collapse whitespace; return None for empty strings so validation can catch them."""
    if raw is None:
        return None
    cleaned = re.sub(r"\s+", " ", raw).strip()
    return cleaned or None

"""Request validation for the API: shape and types only.

Business rules (price sanity, UTC, reason required ...) live in ``crawlers.pipelines`` and run
through ``validate_item``, the same function the scrapers use. Do not duplicate them here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rest_framework import serializers

from crawlers.items import PriceItem


class PriceEntrySerializer(serializers.Serializer):
    source = serializers.CharField(max_length=100)
    node = serializers.CharField(max_length=100)
    # CharField, not DateTimeField: DRF's DateTimeField silently ASSUMES a timezone for naive
    # input. For market data that is a data-corruption bug, so we require an explicit offset.
    interval_start_utc = serializers.CharField()
    interval_minutes = serializers.IntegerField(min_value=1, max_value=1440, default=60)
    price_usd_mwh = serializers.DecimalField(max_digits=12, decimal_places=4)
    reason = serializers.CharField(max_length=500)

    def validate_interval_start_utc(self, value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise serializers.ValidationError("not an ISO 8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise serializers.ValidationError(
                "timestamp needs an explicit UTC offset, e.g. 2026-06-15T04:00:00Z"
            )
        return parsed.astimezone(UTC)


def build_item(data: dict, entered_by: str) -> PriceItem:
    """Validated request data -> the same PriceItem the scrapers produce."""
    return PriceItem(
        source=data["source"],
        node=data["node"],
        interval_start_utc=data["interval_start_utc"],
        interval_minutes=data["interval_minutes"],
        price_usd_mwh=data["price_usd_mwh"],
        local_label="manual entry",
        origin="manual",
        entered_by=entered_by,  # from the authenticated identity, never from the request body
        reason=data["reason"],
    )

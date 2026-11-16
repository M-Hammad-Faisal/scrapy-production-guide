from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from crawlers.utils.parsing import clean_text, parse_availability, parse_price, parse_rating
from crawlers.utils.timeutils import hours_in_local_day, interval_start_utc

NY = "America/New_York"


class TestParsing:
    def test_price_uses_decimal(self):
        assert parse_price("£51.77") == Decimal("51.77")
        assert parse_price("$1,234.50") == Decimal("1234.50")
        assert parse_price("-8.40") == Decimal("-8.40")  # negative power prices are real

    @pytest.mark.parametrize("raw", [None, "", "N/A", "free"])
    def test_price_none_when_not_a_number(self, raw):
        assert parse_price(raw) is None

    def test_rating_availability_text(self):
        assert parse_rating("star-rating Three") == 3
        assert parse_rating("star-rating") is None
        assert parse_availability("In stock (22 available)") == 22
        assert parse_availability("Out of stock") is None
        assert clean_text("  a \n b  ") == "a b"
        assert clean_text("   ") is None


class TestDaylightSaving:
    def test_normal_day_has_24_hours(self):
        assert hours_in_local_day(date(2026, 6, 15), NY) == 24
        # hour ending 1 = 00:00-01:00 EDT (UTC-4) = 04:00 UTC
        assert interval_start_utc(date(2026, 6, 15), 1, NY) == datetime(2026, 6, 15, 4, tzinfo=UTC)

    def test_spring_forward_day_has_23_hours(self):
        assert hours_in_local_day(date(2026, 3, 8), NY) == 23

    def test_spring_forward_missing_hour_is_an_error(self):
        # 02:00-03:00 local does not exist on 2026-03-08, so hour_ending 3 cannot be valid.
        with pytest.raises(ValueError, match="does not exist"):
            interval_start_utc(date(2026, 3, 8), 3, NY)

    def test_spring_forward_offset_changes_across_the_gap(self):
        before = interval_start_utc(date(2026, 3, 8), 2, NY)  # 01:00 EST
        after = interval_start_utc(date(2026, 3, 8), 4, NY)  # 03:00 EDT
        assert before == datetime(2026, 3, 8, 6, tzinfo=UTC)
        assert after == datetime(2026, 3, 8, 7, tzinfo=UTC)  # only one hour later in UTC

    def test_fall_back_day_has_25_hours(self):
        assert hours_in_local_day(date(2026, 11, 1), NY) == 25

    def test_fall_back_repeated_hour_maps_to_two_distinct_instants(self):
        first = interval_start_utc(date(2026, 11, 1), 2, NY, second_occurrence=False)
        second = interval_start_utc(date(2026, 11, 1), 2, NY, second_occurrence=True)
        assert first == datetime(2026, 11, 1, 5, tzinfo=UTC)  # 01:00 EDT
        assert second == datetime(2026, 11, 1, 6, tzinfo=UTC)  # 01:00 EST
        # A key built from LOCAL time would collide here; the UTC key does not.
        assert first != second

    def test_second_occurrence_on_normal_hour_is_an_error(self):
        with pytest.raises(ValueError, match="not an ambiguous hour"):
            interval_start_utc(date(2026, 6, 15), 5, NY, second_occurrence=True)

    def test_hour_ending_out_of_range(self):
        with pytest.raises(ValueError):
            interval_start_utc(date(2026, 6, 15), 0, NY)

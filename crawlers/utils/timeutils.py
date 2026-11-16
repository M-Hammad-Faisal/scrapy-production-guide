"""Time handling for market-style time series.

Rules this module enforces (see docs/03-production-gotchas.md, section 5):

* Store UTC. Convert once, at ingest.
* An "hour ending" label names the END of the hour interval in local wall-clock time.
* Daylight saving: one day has 23 hours, one has 25. The repeated hour is ambiguous in local
  time, so the source must say which occurrence it is (``second_occurrence``).
* A local time that does not exist (spring forward) is an error, never silently shifted.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def interval_start_utc(
    local_date: date,
    hour_ending: int,
    tz: str,
    second_occurrence: bool = False,
) -> datetime:
    """Return the UTC start of the hour interval labelled ``hour_ending`` on ``local_date``.

    ``hour_ending=1`` is the interval 00:00-01:00 local; ``hour_ending=24`` is 23:00-24:00.
    On the fall-back day the interval 01:00-02:00 occurs twice; pass ``second_occurrence=True``
    for the later one (standard time).
    """
    if not 1 <= hour_ending <= 25:
        raise ValueError(f"hour_ending out of range: {hour_ending}")
    zone = ZoneInfo(tz)
    wall_start = datetime.combine(local_date, time(0)) + timedelta(hours=hour_ending - 1)

    first = wall_start.replace(tzinfo=zone, fold=0)
    second = wall_start.replace(tzinfo=zone, fold=1)
    ambiguous = first.utcoffset() != second.utcoffset()

    if second_occurrence and not ambiguous:
        raise ValueError(
            f"{wall_start} {tz} is not an ambiguous hour; unexpected second occurrence"
        )

    chosen = second if second_occurrence else first
    as_utc = chosen.astimezone(UTC)
    # Round trip detects wall-clock times that do not exist (spring-forward gap).
    if as_utc.astimezone(zone).replace(tzinfo=None) != wall_start:
        raise ValueError(f"{wall_start} does not exist in {tz} (daylight saving gap)")
    return as_utc


def hours_in_local_day(local_date: date, tz: str) -> int:
    """23, 24 or 25: how many hourly intervals the local calendar day contains."""
    zone = ZoneInfo(tz)
    start = datetime.combine(local_date, time(0), tzinfo=zone).astimezone(UTC)
    end = datetime.combine(local_date + timedelta(days=1), time(0), tzinfo=zone).astimezone(UTC)
    return int((end - start).total_seconds() // 3600)

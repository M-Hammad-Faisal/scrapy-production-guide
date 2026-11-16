"""Generate the mock ISO price files in mock_iso/ (already committed; rerun to regenerate).

Days chosen on purpose:
  2026-03-08  spring-forward: 23 hours, local hour 02:00-03:00 does not exist (no hour_ending 3)
  2026-06-15  normal 24-hour day, plus one "N/A" price and one absurd price (validation drops them)
  2026-06-16  normal day but ZONE_B is missing one hour (gap detection)
  2026-11-01  fall-back: 25 hours, hour_ending 2 appears twice (second has dst_flag=1)
  2026-06-17  intentionally absent (the server returns 404; the errback counts it)
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "mock_iso"
NODES = ["HUB_A", "ZONE_B"]


def price(node: str, slot: int) -> str:
    base = 32 + (6 if node == "ZONE_B" else 0)
    return f"{base + 14 * math.sin(slot / 3.7):.2f}"


def hour_endings(day: str) -> list[tuple[int, int]]:
    """(hour_ending, dst_flag) pairs for the given day."""
    if day == "2026-03-08":
        return [(h, 0) for h in range(1, 25) if h != 3]  # 23 hours
    if day == "2026-11-01":
        rows = [(h, 0) for h in range(1, 3)] + [(2, 1)] + [(h, 0) for h in range(3, 25)]
        return rows  # 25 hours; hour_ending 2 twice
    return [(h, 0) for h in range(1, 25)]


def write_day(day: str, mutate=None) -> None:
    rows = []
    for node in NODES:
        for slot, (he, flag) in enumerate(hour_endings(day)):
            rows.append([day, he, flag, node, price(node, slot)])
    if mutate:
        rows = mutate(rows)
    OUT.mkdir(exist_ok=True)
    with open(OUT / f"prices_{day}.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "hour_ending", "dst_flag", "node", "lmp_usd_mwh"])
        writer.writerows(rows)


def with_defects(rows: list[list]) -> list[list]:
    rows[5][4] = "N/A"  # missing price -> validation drop
    rows[30][4] = "99999.00"  # absurd price -> validation drop
    rows[12][4] = "-8.40"  # negative prices are REAL in power markets; must pass
    return rows


def missing_hour(rows: list[list]) -> list[list]:
    return [r for r in rows if not (r[3] == "ZONE_B" and r[1] == 7)]


if __name__ == "__main__":
    write_day("2026-03-08")
    write_day("2026-06-15", with_defects)
    write_day("2026-06-16", missing_hour)
    write_day("2026-11-01")
    print(f"wrote mock files to {OUT}")

"""Flag prices that are probably wrong, so the map can leave them out.

Fuel prices depend a lot on the area (motorways, islands, borders), so each price is
compared with the median of nearby stations selling the same fuel in the same service
mode, not with a national average. A price is suspect when it is

  * more than ``LOW`` below that local median (old data, typos, wrong product) and no
    other nearby station has about the same price, or
  * more than ``HIGH`` times it (typos such as 18.1 for 1.81). Moderately high prices
    are left alone: expensive motorway stations are real.

The second condition keeps real local price levels, such as duty-free zones or a
category that mixes two products with different prices: a single station far below
its neighbours is an error, several stations agreeing on a low price are not.

Stations with too few neighbours are compared with the country-wide median instead,
with a wider margin. Prices older than the plugin's ``max_price_age`` are checked but
not used as reference, since the map hides them anyway.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from fuelprice.core.models import Dataset, FuelCategory, Price, Station

K = 20
"""Number of nearest stations the local median is computed from."""
RADIUS_KM = 30.0
"""Stations farther away than this are not neighbours."""
MIN_NEIGHBOURS = 5
"""Below this, fall back to the country-wide median."""
LOW = 0.12
FALLBACK_LOW = 0.20
WIDE_LOW = 0.35
WIDE_FALLBACK_LOW = 0.40
WIDE_CATEGORIES = frozenset({FuelCategory.CNG, FuelCategory.LNG})
"""Gas prices vary much more between nearby stations than liquid fuels: wider margins."""
HIGH = 2.0
SUPPORT = 0.03
"""A neighbour within this fraction of a low price confirms it..."""
MIN_SUPPORT = 1
"""...when there are at least this many of them (Livigno, duty free, has just two stations)."""
CELL_KM = 5.0

GroupKey = tuple[FuelCategory, bool | None]
Point = tuple[float, float, float, str]  # x km, y km, price, station id


def flag_outliers(dataset: Dataset, max_age: timedelta | None = None) -> int:
    """Set ``Price.suspect`` on every price of ``dataset``; returns how many are suspect."""
    cutoff = dataset.fetched_at - max_age if max_age is not None else None
    groups: dict[GroupKey, list[tuple[Station, Price]]] = defaultdict(list)
    for s in dataset.stations:
        for p in s.prices:
            p.suspect = False
            groups[(p.category, p.self_service)].append((s, p))
    return sum(
        _flag_group(entries, cutoff, wide=category in WIDE_CATEGORIES)
        for (category, _), entries in groups.items()
    )


def _is_fresh(p: Price, cutoff: datetime | None) -> bool:
    return cutoff is None or p.updated_at is None or p.updated_at >= cutoff


def _flag_group(entries: list[tuple[Station, Price]], cutoff: datetime | None, wide: bool = False) -> int:
    local_low, fallback_low = (WIDE_LOW, WIDE_FALLBACK_LOW) if wide else (LOW, FALLBACK_LOW)
    refs = [(s, p) for s, p in entries if p.price > 0 and _is_fresh(p, cutoff)]
    # Equirectangular projection to km: accurate enough at country scale.
    lat0 = math.radians(sum(s.lat for s, _ in refs) / len(refs)) if refs else 0.0
    kx, ky = 111.32 * math.cos(lat0), 110.57

    grid: dict[tuple[int, int], list[Point]] = defaultdict(list)
    for s, p in refs:
        x, y = s.lon * kx, s.lat * ky
        grid[(int(x // CELL_KM), int(y // CELL_KM))].append((x, y, p.price, s.id))
    overall = median(p.price for _, p in refs) if refs else None

    flagged = 0
    for s, p in entries:
        if p.price <= 0:
            p.suspect = True
        elif overall is not None:
            near = _nearest(grid, s.lon * kx, s.lat * ky, s.id)
            ref, low = (median(near), local_low) if len(near) >= MIN_NEIGHBOURS else (overall, fallback_low)
            too_low = p.price < ref * (1 - low) and not _confirmed(p.price, near)
            p.suspect = too_low or p.price > ref * HIGH
        flagged += p.suspect
    return flagged


def _confirmed(price: float, near: list[float]) -> bool:
    return sum(abs(q - price) <= price * SUPPORT for q in near) >= MIN_SUPPORT


def _nearest(grid: dict[tuple[int, int], list[Point]], x: float, y: float, station_id: str) -> list[float]:
    """Prices of the ``K`` nearest other stations within ``RADIUS_KM``."""
    cx, cy = int(x // CELL_KM), int(y // CELL_KM)
    found: list[tuple[float, float]] = []  # (squared distance, price)
    for r in range(math.ceil(RADIUS_KM / CELL_KM) + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue  # only the ring at distance r; inner cells were visited already
                for px, py, price, sid in grid.get((cx + dx, cy + dy), ()):
                    d2 = (px - x) ** 2 + (py - y) ** 2
                    if sid != station_id and d2 <= RADIUS_KM**2:
                        found.append((d2, price))
        # Every cell not visited yet is at least r cells away.
        if len(found) >= K and heapq.nsmallest(K, found)[-1][0] <= (r * CELL_KM) ** 2:
            break
    return [price for _, price in heapq.nsmallest(K, found)]

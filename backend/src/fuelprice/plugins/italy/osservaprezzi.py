"""Parsing of the MIMIT "Osservaprezzi" API (carburanti.mise.gov.it/ospzApi).

Used as the primary Italian source because, unlike www.mimit.gov.it, it is
reachable from cloud servers such as GitHub's. ``POST /search/area {"region": id}``
returns every station of a region with live prices, but with a single
``insertDate`` per station instead of a date per price.

Per-price dates are estimated from the price ids, which grow over time: each
station's newest price id is paired with the station's ``insertDate``, which gives
an id -> date calibration curve. A price whose id is older than the whole curve
(e.g. a price set years ago and never updated) gets the oldest date of the curve,
a lower bound on its age, so the app's max-age filter drops it.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from fuelprice.core.models import Price, Station
from fuelprice.core.parsing import clean, number, valid_price
from fuelprice.plugins.italy.fuels import categorize
from fuelprice.plugins.italy.parser import LAT_RANGE, LON_RANGE

# Brand spellings used by the API -> spelling used by the CSV source.
BRANDS = {
    "AgipEni": "Agip Eni",
    "PompeBianche": "Pompe Bianche",
    "AFPetroli": "AF Petroli",
}

_PROVINCE = re.compile(r"^(.*\S)\s+([A-Z]{2})$")


def split_address(raw: str | None) -> tuple[str, str, str]:
    """``"VIA FAUSTA 207 30013 - CAVALLINO-TREPORTI VE"`` -> (street, city, province)."""
    text = clean(raw)
    street, sep, place = text.rpartition(" - ")
    if not sep:
        return text, "", ""
    street = street.rstrip(" -")
    m = _PROVINCE.match(place)
    if not m:
        return street, place, ""
    return street, m.group(1), m.group(2)


class PriceDateEstimator:
    """Estimates when a price was set from its id (see module docstring)."""

    def __init__(self, results: Iterable[dict[str, Any]]):
        pairs = []
        for r in results:
            ids = [f["id"] for f in r.get("fuels") or [] if isinstance(f.get("id"), int)]
            when = _parse_dt(r.get("insertDate"))
            if ids and when:
                pairs.append((max(ids), when.timestamp()))
        pairs.sort()
        self._ids = [i for i, _ in pairs]
        # Running maximum keeps the curve monotonic despite small id/date disorder.
        self._ts: list[float] = []
        latest = float("-inf")
        for _, ts in pairs:
            latest = max(latest, ts)
            self._ts.append(latest)
        self.oldest = datetime.fromtimestamp(min(ts for _, ts in pairs), UTC) if pairs else None

    def estimate(self, price_id: int | None, station_date: datetime | None) -> datetime | None:
        if price_id is None or not self._ids:
            return station_date
        k = bisect.bisect_right(self._ids, price_id) - 1
        if k < 0:
            return self.oldest  # older than every station's latest update
        estimate = datetime.fromtimestamp(self._ts[k], UTC)
        # A price can't be newer than the station's last communication.
        return min(estimate, station_date) if station_date else estimate


def _parse_dt(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def parse_area_results(results: list[dict[str, Any]]) -> list[Station]:
    estimator = PriceDateEstimator(results)
    stations: dict[str, Station] = {}
    for r in results:
        loc = r.get("location") or {}
        lat, lon = number(loc.get("lat")), number(loc.get("lng"))
        if lat is None or lon is None:
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            continue
        station_date = _parse_dt(r.get("insertDate"))
        prices = []
        for f in r.get("fuels") or []:
            price = valid_price(f.get("price"))
            product = clean(f.get("name"))
            if price is None or not product:
                continue
            prices.append(Price(
                category=categorize(product),
                product=product,
                price=price,
                self_service=bool(f.get("isSelf")),
                updated_at=estimator.estimate(f.get("id"), station_date),
            ))
        if not prices:
            continue
        street, city, province = split_address(r.get("address"))
        brand = clean(r.get("brand"))
        brand = BRANDS.get(brand, brand)
        sid = str(r["id"])
        stations[sid] = Station(
            id=sid,
            name=clean(r.get("name")) or brand,
            brand=brand,
            address=street,
            city=city,
            province=province,
            lat=lat,
            lon=lon,
            prices=prices,
        )
    return list(stations.values())

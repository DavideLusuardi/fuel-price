"""Pure parsing of the E-Control Spritpreisrechner API.

``/regions`` lists the nine states (``BL``) with their political districts (``PB``)
in ``subRegions``. ``/search/gas-stations/by-region`` returns, for one district and
one fuel type, its cheapest stations (at most five with a price)::

    {"id": 1474414, "name": "Diskont Tankstelle",
     "location": {"address": "...", "postalCode": "7000", "city": "Eisenstadt",
                  "latitude": 47.825, "longitude": 16.5319},
     "open": true, "prices": [{"fuelType": "SUP", "amount": 1.639, "label": "Super 95"}]}

The search results of all districts and fuels are merged by station ``id``. There
are no brands and no price timestamps.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from fuelprice.core.models import Dataset, Price, Station
from fuelprice.core.models import FuelCategory as F
from fuelprice.core.parsing import clean, number, valid_price

LAT_RANGE = (46.3, 49.1)
LON_RANGE = (9.5, 17.2)

# E-Control fuel type -> (category, product name).
FUELS: dict[str, tuple[F, str]] = {
    "SUP": (F.PETROL, "Super 95"),
    "DIE": (F.DIESEL, "Diesel"),
    "GAS": (F.CNG, "CNG (Erdgas)"),
}


def districts(regions: Iterable[Mapping[str, Any]]) -> dict[int, str]:
    """Political district code -> state name, from the ``/regions`` tree."""
    out: dict[int, str] = {}
    for state in regions:
        for sub in state.get("subRegions") or []:
            if sub.get("type") == "PB" and sub.get("code") is not None:
                out[int(sub["code"])] = clean(state.get("name"))
    return out


def _coords(location: Mapping[str, Any]) -> tuple[float, float] | None:
    lat, lon = number(location.get("latitude")), number(location.get("longitude"))
    if lat is None or lon is None:
        return None
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        return None
    return lat, lon


def _station(row: Mapping[str, Any], province: str, lat: float, lon: float) -> Station:
    loc = row.get("location") or {}
    return Station(
        id=str(row["id"]),
        name=clean(row.get("name")),
        address=clean(loc.get("address")),
        city=" ".join(filter(None, [clean(loc.get("postalCode")), clean(loc.get("city"))])),
        province=province,
        lat=lat,
        lon=lon,
    )


def build_dataset(results: Iterable[tuple[str, str, Iterable[Mapping[str, Any]]]]) -> Dataset:
    """``results`` holds one ``(state name, fuel type, search rows)`` per search."""
    stations: dict[str, Station] = {}
    for province, fuel, rows in results:
        if fuel not in FUELS:
            continue
        category, product = FUELS[fuel]
        for row in rows:
            if row.get("id") is None:
                continue
            amount = next((valid_price(p.get("amount")) for p in row.get("prices") or []
                           if p.get("fuelType") == fuel), None)
            coords = _coords(row.get("location") or {})
            if amount is None or coords is None:
                continue
            key = str(row["id"])
            station = stations.get(key)
            if station is None:
                station = stations[key] = _station(row, province, *coords)
            if any(p.category is category for p in station.prices):
                continue  # same station found again through a neighbouring district
            station.prices.append(Price(category=category, product=product, price=amount))
    return Dataset(stations=list(stations.values()), data_date=None, fetched_at=datetime.now(UTC))

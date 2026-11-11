"""Pure parsing of gasvaktin's ``gas.min.json``.

``{"stations": [{"key", "name", "company", "geo": {"lat", "lon"}, "bensin95",
"diesel", "bensin95_discount", "diesel_discount"}]}``. Prices are in krónur per litre.
The ``*_discount`` prices need a company's loyalty key or card and are skipped.
There are no per-price dates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fuelprice.core.models import Dataset, Price, Station
from fuelprice.core.models import FuelCategory as F
from fuelprice.core.parsing import clean, number, valid_price

# ISK per litre (about 240-345 in 2026): the euro PRICE_RANGE doesn't apply.
PRICE_RANGE_ISK = (100.0, 600.0)
LAT_RANGE = (63.0, 67.0)
LON_RANGE = (-25.0, -13.0)

FUELS: dict[str, tuple[F, str]] = {
    "bensin95": (F.PETROL, "Bensín 95"),
    "diesel": (F.DIESEL, "Dísel"),
}


def _coords(geo: Any) -> tuple[float, float] | None:
    if not isinstance(geo, dict):
        return None
    lat, lon = number(geo.get("lat")), number(geo.get("lon"))
    if lat is None or lon is None:
        return None
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        return None
    return lat, lon


def build_dataset(data: dict[str, Any]) -> Dataset:
    stations: list[Station] = []
    for s in data.get("stations") or []:
        coords = _coords(s.get("geo"))
        if coords is None:
            continue
        prices = [
            Price(category=category, product=product, price=price)
            for key, (category, product) in FUELS.items()
            if (price := valid_price(s.get(key), PRICE_RANGE_ISK)) is not None
        ]
        if not prices:
            continue
        company = clean(s.get("company"))
        lat, lon = coords
        stations.append(Station(
            id=clean(s.get("key")),
            name=clean(s.get("name")) or company,
            brand=company,
            lat=lat,
            lon=lon,
            prices=prices,
        ))
    return Dataset(stations=stations, data_date=None, fetched_at=datetime.now(UTC))

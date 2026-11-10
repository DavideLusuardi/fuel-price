"""Pure parsing of the goriva.si API responses (no network access)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fuelprice.core.models import FuelCategory as F
from fuelprice.core.models import Price, Station
from fuelprice.core.parsing import clean, number, valid_price

# goriva.si fuel code -> (category, product label). KOEL (heating oil) is omitted on purpose.
FUELS: dict[str, tuple[F, str]] = {
    "95": (F.PETROL, "NMB-95"),
    "dizel": (F.DIESEL, "Dizel"),
    "98": (F.PREMIUM_PETROL, "NMB-98"),
    "100": (F.PREMIUM_PETROL, "NMB-100"),
    "dizel-premium": (F.PREMIUM_DIESEL, "Dizel Premium"),
    "avtoplin-lpg": (F.LPG, "LPG"),
    "hvo": (F.HVO, "HVO"),
    "cng": (F.CNG, "CNG"),
    "lng": (F.LNG, "LNG"),
}

LAT_RANGE = (45.3, 47.0)
LON_RANGE = (13.3, 16.7)


def parse_franchises(data: Iterable[dict[str, Any]]) -> dict[int, str]:
    return {int(f["pk"]): clean(f.get("name")) for f in data if f.get("pk") is not None}


def parse_stations(results: Iterable[dict[str, Any]], franchises: dict[int, str]) -> list[Station]:
    stations: list[Station] = []
    for r in results:
        lat, lon = number(r.get("lat")), number(r.get("lng"))
        if lat is None or lon is None:
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            continue
        prices = []
        for code, raw in (r.get("prices") or {}).items():
            fuel = FUELS.get(code)
            price = valid_price(raw)
            if fuel is None or price is None:
                continue
            category, label = fuel
            prices.append(Price(category=category, product=label, price=price))
        if not prices:
            continue
        brand = franchises.get(r.get("franchise"), "")  # type: ignore[arg-type]
        stations.append(Station(
            id=str(r["pk"]),
            name=clean(r.get("name")) or brand,
            brand=brand,
            address=clean(r.get("address")),
            city=clean(r.get("zip_code")),
            lat=lat,
            lon=lon,
            prices=prices,
        ))
    return stations

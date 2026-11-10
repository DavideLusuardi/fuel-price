"""Pure parsing of the Croatian ministry price data (mzoe-gor.hr ``data.gz``)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from fuelprice.core.models import Dataset, Price, Station
from fuelprice.core.models import FuelCategory as F
from fuelprice.core.parsing import PRICE_RANGE, clean, number

LAT_RANGE = (42.0, 46.7)
LON_RANGE = (13.0, 19.7)

# vrsta_goriva_id -> category. Everything else (heating oil, agricultural "blue"
# diesel, bio components, bottled LPG, EV charging) is not a road fuel and is dropped.
VRSTA: dict[int, F] = {
    1: F.PETROL,  # Eurosuper 95 with additives
    2: F.PETROL,  # Eurosuper 95 without additives
    5: F.PREMIUM_PETROL,  # Eurosuper 100 with additives
    6: F.PREMIUM_PETROL,  # Eurosuper 100 without additives
    7: F.DIESEL,  # Eurodiesel with additives
    8: F.DIESEL,  # Eurodiesel without additives
    9: F.LPG,  # UNP (autoplin)
    26: F.CNG,  # Stlačeni prirodni plin
}
_PREMIUM = re.compile(r"premium|v-?power|g-?power|ultimate|excellium|imperium|platin|gold", re.I)
_UPGRADE = {F.PETROL: F.PREMIUM_PETROL, F.DIESEL: F.PREMIUM_DIESEL}

_DMS = re.compile(
    r"""^\s*(\d+(?:\.\d+)?)\s*°\s*(?:(\d+(?:\.\d+)?)\s*['′])?\s*(?:(\d+(?:\.\d+)?)\s*["″])?\s*([NSEW])?\s*$""",
    re.I,
)


def parse_coord(value: object) -> float | None:
    """Decimal degrees or degrees/minutes(/seconds) like ``45° 39.4112' N``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if (n := number(text)) is not None:
        return n
    m = _DMS.match(text)
    if not m:
        return None
    deg, minutes, seconds, hemi = m.groups()
    result = float(deg) + float(minutes or 0) / 60 + float(seconds or 0) / 3600
    return -result if hemi and hemi.upper() in "SW" else result


def resolve_lat_lon(a: float | None, b: float | None) -> tuple[float, float] | None:
    """The source's ``long``/``lat`` fields are usually swapped: assign by value range."""
    if a is None or b is None:
        return None

    def is_lat(v: float) -> bool:
        return LAT_RANGE[0] <= v <= LAT_RANGE[1]

    def is_lon(v: float) -> bool:
        return LON_RANGE[0] <= v <= LON_RANGE[1]

    if is_lat(a) and is_lon(b):
        return a, b
    if is_lat(b) and is_lon(a):
        return b, a
    return None


def categorize(vrsta_id: int | None, product: str | None) -> F | None:
    category = VRSTA.get(vrsta_id) if vrsta_id is not None else None
    if category in _UPGRADE and product and _PREMIUM.search(product):
        return _UPGRADE[category]
    return category


def build_dataset(data: dict[str, Any], data_date: date | None) -> Dataset:
    products = {g["id"]: g for g in data.get("gorivos", [])}
    kinds = {v["id"]: clean(v.get("vrsta_goriva")) for v in data.get("vrsta_gorivas", [])}
    companies = {o["id"]: clean(o.get("naziv")) for o in data.get("obvezniks", [])}

    stations: list[Station] = []
    for p in data.get("postajas", []):
        coords = resolve_lat_lon(parse_coord(p.get("long")), parse_coord(p.get("lat")))
        if coords is None:
            continue
        prices: list[Price] = []
        legacy_currency = False
        for c in p.get("cjenici") or []:
            product = products.get(c.get("gorivo_id"))
            if product is None:
                continue
            vrsta = product.get("vrsta_goriva_id")
            name = clean(product.get("naziv")) or kinds.get(vrsta, "")
            category = categorize(vrsta, name)
            price = number(c.get("cijena"))
            if category is None or price is None:
                continue
            if price > PRICE_RANGE[1]:
                # Prices never updated since the switch from kuna to euro (2023).
                legacy_currency = True
                break
            if price < PRICE_RANGE[0]:
                continue
            prices.append(Price(category=category, product=name, price=price))
        if legacy_currency or not prices:
            continue
        company = companies.get(p.get("obveznik_id"), "")
        lat, lon = coords
        stations.append(Station(
            id=str(p["id"]),
            name=clean(p.get("naziv")) or company,
            brand=company,
            operator=company,
            address=clean(p.get("adresa")),
            city=clean(p.get("mjesto")),
            lat=lat,
            lon=lon,
            prices=prices,
        ))
    return Dataset(stations=stations, data_date=data_date, fetched_at=datetime.now(UTC))

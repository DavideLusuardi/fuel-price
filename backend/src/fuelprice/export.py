"""Compact JSON format of the static data files read by the web app.

One file per country (``<code>.json``) plus ``meta.json``. Stations and prices are
arrays instead of objects, and product names are stored once, so the Italian file
is ~5 MB raw / ~1 MB gzipped instead of ~16 MB.

Country file::

    {"v": 1, "data_date": "2026-11-09" | null, "fetched_at": "<iso>",
     "products": [[name, category], ...],
     "stations": [[id, name, brand, operator, address, city, province, lat, lon,
                   [[product_index, price, self (1 | 0 | null), updated_at, seen_since, suspect (1 | 0)], ...]], ...]}

``updated_at`` and ``seen_since`` are Unix timestamps in seconds, or null. ``suspect``
marks prices that look wrong (see ``core/outliers.py``); version 1 files lack it.
Keep ``frontend/src/types.ts`` in sync with this format.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from fuelprice.core.models import Dataset, FuelCategory, Price, Station

FORMAT_VERSION = 2
READABLE_VERSIONS = (1, 2)


def _ts(dt: datetime | None) -> int | None:
    return int(dt.timestamp()) if dt else None


def _dt(ts: int | None) -> datetime | None:
    return datetime.fromtimestamp(ts, UTC) if ts is not None else None


def encode_country(dataset: Dataset) -> dict[str, Any]:
    products: dict[tuple[str, FuelCategory], int] = {}
    stations = []
    for s in dataset.stations:
        prices = []
        for p in s.prices:
            idx = products.setdefault((p.product, p.category), len(products))
            self_flag = None if p.self_service is None else int(p.self_service)
            prices.append([idx, p.price, self_flag, _ts(p.updated_at), _ts(p.seen_since), int(p.suspect)])
        stations.append([
            s.id, s.name, s.brand, s.operator, s.address, s.city, s.province,
            round(s.lat, 6), round(s.lon, 6), prices,
        ])
    return {
        "v": FORMAT_VERSION,
        "data_date": dataset.data_date.isoformat() if dataset.data_date else None,
        "fetched_at": dataset.fetched_at.isoformat(),
        "products": [[name, category.value] for (name, category) in products],
        "stations": stations,
    }


def decode_country(doc: dict[str, Any]) -> Dataset:
    if doc.get("v") not in READABLE_VERSIONS:
        raise ValueError(f"Unsupported data format version {doc.get('v')!r}")
    products = [(name, FuelCategory(cat)) for name, cat in doc["products"]]
    stations = []
    for sid, name, brand, operator, address, city, province, lat, lon, prices in doc["stations"]:
        stations.append(Station(
            id=sid, name=name, brand=brand, operator=operator, address=address, city=city,
            province=province, lat=lat, lon=lon,
            prices=[
                Price(
                    category=products[idx][1],
                    product=products[idx][0],
                    price=price,
                    self_service=None if self_flag is None else bool(self_flag),
                    updated_at=_dt(updated),
                    seen_since=_dt(since),
                    suspect=bool(rest and rest[0]),
                )
                for idx, price, self_flag, updated, since, *rest in prices
            ],
        ))
    return Dataset(
        stations=stations,
        data_date=date.fromisoformat(doc["data_date"]) if doc.get("data_date") else None,
        fetched_at=datetime.fromisoformat(doc["fetched_at"]),
    )


def dumps(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()

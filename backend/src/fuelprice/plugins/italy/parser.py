"""Pure parsing of the MIMIT open-data CSV files (no network access).

File format (both files):
    line 1: ``Estrazione del YYYY-MM-DD``
    line 2: header
    rest:   ``|``-separated rows, no quoting
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fuelprice.core.models import Dataset, Price, Station
from fuelprice.core.parsing import clean as _clean
from fuelprice.core.parsing import number as _number
from fuelprice.core.parsing import valid_price
from fuelprice.plugins.italy.fuels import categorize

log = logging.getLogger(__name__)
ROME = ZoneInfo("Europe/Rome")

# Rough bounding box of Italy (incl. islands, San Marino, Vatican).
LAT_RANGE = (35.0, 47.5)
LON_RANGE = (6.0, 19.0)
STATION_FIELDS = 10
PRICE_FIELDS = 5


def _split_header(text: str) -> tuple[date | None, list[str]]:
    lines = text.splitlines()
    data_date = None
    if lines:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", lines[0])
        if m:
            data_date = date.fromisoformat(m.group(1))
    return data_date, lines[2:]  # skip date line + header


def parse_stations(text: str) -> tuple[date | None, dict[str, Station]]:
    data_date, lines = _split_header(text)
    stations: dict[str, Station] = {}
    for line in lines:
        if not line.strip():
            continue
        cols = line.split("|")
        if len(cols) < STATION_FIELDS:
            log.debug("Skipping short station row: %r", line)
            continue
        if len(cols) > STATION_FIELDS:
            # Unescaped '|' inside the station name: the address is the last
            # middle column, everything before it belongs to the name.
            extra = len(cols) - STATION_FIELDS
            name = "|".join(cols[4 : 5 + extra])
            cols = [*cols[:4], name, *cols[5 + extra :]]
        sid, operator, brand, _kind, name, address, city, province, lat_s, lon_s = cols
        lat, lon = _number(lat_s), _number(lon_s)
        if lat is None or lon is None:
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            continue
        sid = sid.strip()
        stations[sid] = Station(
            id=sid,
            name=_clean(name) or _clean(brand),
            brand=_clean(brand),
            operator=_clean(operator),
            address=_clean(address),
            city=_clean(city),
            province=_clean(province),
            lat=lat,
            lon=lon,
        )
    return data_date, stations


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y %H:%M:%S").replace(tzinfo=ROME)
    except ValueError:
        return None


def parse_prices(text: str) -> tuple[date | None, Iterator[tuple[str, Price]]]:
    data_date, lines = _split_header(text)

    def rows() -> Iterator[tuple[str, Price]]:
        for line in lines:
            cols = line.split("|")
            if len(cols) != PRICE_FIELDS:
                continue
            sid, product, price_s, is_self, dt = cols
            price = valid_price(price_s)
            if price is None:
                continue
            product = _clean(product)
            yield sid.strip(), Price(
                category=categorize(product),
                product=product,
                price=price,
                self_service=is_self.strip() == "1",
                updated_at=_parse_dt(dt),
            )

    return data_date, rows()


def build_dataset(stations_csv: str, prices_csv: str) -> Dataset:
    station_date, stations = parse_stations(stations_csv)
    price_date, rows = parse_prices(prices_csv)
    for sid, price in rows:
        station = stations.get(sid)
        if station is not None:
            station.prices.append(price)
    return Dataset(
        stations=[s for s in stations.values() if s.prices],
        data_date=price_date or station_date,
        fetched_at=datetime.now(UTC),
    )

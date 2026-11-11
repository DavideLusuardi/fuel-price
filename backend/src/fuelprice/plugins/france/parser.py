"""Pure parsing of the French "flux instantané" (prix-carburants.gouv.fr open data).

One ISO-8859-1 XML document::

    <pdv_liste>
      <pdv id="38230003" latitude="4574500" longitude="518300" cp="38230" pop="R|A">
        <adresse>…</adresse> <ville>…</ville> <horaires>…</horaires> <services>…</services>
        <prix nom="Gazole" id="1" maj="2026-11-11 01:17:00" valeur="2.089"/>
        …
      </pdv>
    </pdv_liste>

Coordinates are WGS84 degrees times 100000. ``maj`` is Paris local time. ``pop`` is
"A" for motorway stations ("autoroute") and "R" for the others ("route").
The feed has no station names or brands.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fuelprice.core.models import Dataset, Price, Station
from fuelprice.core.models import FuelCategory as F
from fuelprice.core.parsing import clean, number, valid_price

PARIS = ZoneInfo("Europe/Paris")
COORD_SCALE = 100_000
# Mainland France and Corsica: the feed has no overseas departments.
LAT_RANGE = (41.0, 51.5)
LON_RANGE = (-5.5, 10.0)

FUELS: dict[str, F] = {
    "Gazole": F.DIESEL,
    "SP95": F.PETROL,
    "E10": F.PETROL,  # SP95-E10, 95 octane
    "SP98": F.PREMIUM_PETROL,
    "GPLc": F.LPG,
    "E85": F.OTHER,  # superethanol, flex-fuel cars only
}


def categorize(name: str) -> F | None:
    return FUELS.get(name)


def parse_maj(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=PARIS)
    except ValueError:
        return None


def _coords(pdv: ET.Element) -> tuple[float, float] | None:
    lat, lon = number(pdv.get("latitude")), number(pdv.get("longitude"))
    if lat is None or lon is None:
        return None
    lat, lon = lat / COORD_SCALE, lon / COORD_SCALE
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        return None
    return lat, lon


def build_dataset(xml: bytes) -> Dataset:
    root = ET.fromstring(xml)
    stations: list[Station] = []
    newest: datetime | None = None
    for pdv in root.iter("pdv"):
        coords = _coords(pdv)
        if coords is None:
            continue
        prices: list[Price] = []
        for p in pdv.findall("prix"):
            product = clean(p.get("nom"))
            category = categorize(product)
            price = valid_price(p.get("valeur"))
            if category is None or price is None:
                continue
            updated = parse_maj(p.get("maj"))
            if updated is not None and (newest is None or updated > newest):
                newest = updated
            prices.append(Price(category=category, product=product, price=price, updated_at=updated))
        if not prices:
            continue
        city = clean(pdv.findtext("ville"))
        lat, lon = coords
        stations.append(Station(
            id=pdv.get("id", ""),
            name=f"{city} (autoroute)" if pdv.get("pop") == "A" else city,
            address=clean(pdv.findtext("adresse")),
            city=" ".join(filter(None, [clean(pdv.get("cp")), city])),
            lat=lat,
            lon=lon,
            prices=prices,
        ))
    return Dataset(
        stations=stations,
        data_date=newest.date() if newest else None,
        fetched_at=datetime.now(UTC),
    )

"""Pure parsing of the DGEG "Preços dos Combustíveis Online" search results.

``PesquisarPostos`` returns one row per station for a single fuel type::

    {"Id": 65653, "Nome": "GALP Sines", "Marca": "GALP", "TipoPosto": "Outro",
     "Combustivel": "Gasóleo simples", "Preco": "2,246 €",
     "DataAtualizacao": "2026-11-11 04:45", "Morada": "...", "Localidade": "...",
     "CodPostal": "7520-...", "Municipio": "...", "Distrito": "Setúbal",
     "Latitude": 37.95, "Longitude": -8.86, "Quantidade": 2958}

The rows of all fuel types are merged by station ``Id``. ``DataAtualizacao`` is
Lisbon local time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fuelprice.core.models import Dataset, Price, Station
from fuelprice.core.models import FuelCategory as F
from fuelprice.core.parsing import clean, number, valid_price

LISBON = ZoneInfo("Europe/Lisbon")
# Mainland Portugal: the source has no Azores or Madeira.
LAT_RANGE = (36.8, 42.2)
LON_RANGE = (-9.6, -6.1)
NO_BRAND = {"genérico", "generico"}

# DGEG fuel type id -> category. Petrol goes by octane, as for the other countries:
# "especial" (additivated) 95 is still petrol. Coloured (agricultural) diesel, heating
# oil, two-stroke mix and CNG priced per m³ are not requested.
FUELS: dict[int, F] = {
    3201: F.PETROL,  # Gasolina simples 95
    3205: F.PETROL,  # Gasolina especial 95
    3400: F.PREMIUM_PETROL,  # Gasolina 98
    3405: F.PREMIUM_PETROL,  # Gasolina especial 98
    2101: F.DIESEL,  # Gasóleo simples
    2105: F.PREMIUM_DIESEL,  # Gasóleo especial
    1120: F.LPG,  # GPL Auto
    1143: F.CNG,  # GNC, €/kg
    1142: F.LNG,  # GNL, €/kg
    2115: F.OTHER,  # Biodiesel B15
}


def parse_price(value: object) -> float | None:
    """``"2,246 €"`` -> 2.246, or None outside the plausible range."""
    return valid_price(clean(value).replace("€", "").strip())


def parse_date(value: object) -> datetime | None:
    try:
        return datetime.strptime(clean(value), "%Y-%m-%d %H:%M").replace(tzinfo=LISBON)
    except ValueError:
        return None


def _coords(row: Mapping[str, Any]) -> tuple[float, float] | None:
    lat, lon = number(row.get("Latitude")), number(row.get("Longitude"))
    if lat is None or lon is None:
        return None
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        return None
    return lat, lon


def _station(row: Mapping[str, Any], lat: float, lon: float) -> Station:
    brand = clean(row.get("Marca"))
    return Station(
        id=str(row["Id"]),
        name=clean(row.get("Nome")) or brand,
        brand="" if brand.lower() in NO_BRAND else brand,
        address=clean(row.get("Morada")),
        city=" ".join(filter(None, [clean(row.get("CodPostal")), clean(row.get("Localidade"))])),
        province=clean(row.get("Distrito")),
        lat=lat,
        lon=lon,
    )


def build_dataset(results: Mapping[int, Iterable[Mapping[str, Any]]]) -> Dataset:
    """``results`` maps each DGEG fuel type id to its search rows."""
    stations: dict[str, Station] = {}
    newest: datetime | None = None
    for fuel_id, rows in results.items():
        category = FUELS.get(fuel_id)
        if category is None:
            continue
        for row in rows:
            if row.get("Id") is None:
                continue
            price = parse_price(row.get("Preco"))
            coords = _coords(row)
            if price is None or coords is None:
                continue
            updated = parse_date(row.get("DataAtualizacao"))
            if updated is not None and (newest is None or updated > newest):
                newest = updated
            station = stations.get(str(row["Id"]))
            if station is None:
                station = stations[str(row["Id"])] = _station(row, *coords)
            station.prices.append(Price(
                category=category,
                product=clean(row.get("Combustivel")),
                price=price,
                updated_at=updated,
            ))
    return Dataset(
        stations=list(stations.values()),
        data_date=newest.date() if newest else None,
        fetched_at=datetime.now(UTC),
    )

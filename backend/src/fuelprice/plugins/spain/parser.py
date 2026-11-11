"""Pure parsing of the Spanish ministry price service (Geoportal de Gasolineras).

One JSON document: ``{"Fecha": "dd/mm/yyyy hh:mm:ss", "ListaEESSPrecio": [...]}``.
Every station has the same keys, one ``"Precio <product>"`` per product, empty when
the station doesn't sell it. Numbers use a decimal comma. There are no per-price dates.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fuelprice.core.models import Dataset, Price, Station
from fuelprice.core.models import FuelCategory as F
from fuelprice.core.parsing import clean, number, valid_price

# Mainland, Balearic and Canary Islands, Ceuta and Melilla.
LAT_RANGE = (27.5, 44.0)
LON_RANGE = (-18.5, 4.5)
PRICE_PREFIX = "Precio "

# Petrol goes by octane, as for the other countries: "95 E5 Premium" is still 95.
# Agricultural diesel (Gasoleo B), AdBlue, hydrogen, methanol and ammonia are dropped.
FUELS: dict[str, F] = {
    "Gasolina 95 E5": F.PETROL,
    "Gasolina 95 E10": F.PETROL,
    "Gasolina 95 E5 Premium": F.PETROL,
    "Gasolina 98 E5": F.PREMIUM_PETROL,
    "Gasolina 98 E10": F.PREMIUM_PETROL,
    "Gasoleo A": F.DIESEL,
    "Gasoleo Premium": F.PREMIUM_DIESEL,
    "Diésel Renovable": F.HVO,
    "Gases licuados del petróleo": F.LPG,
    "Gas Natural Comprimido": F.CNG,
    "Biogas Natural Comprimido": F.CNG,
    "Gas Natural Licuado": F.LNG,
    "Biogas Natural Licuado": F.LNG,
    "Gasolina 95 E25": F.OTHER,
    "Gasolina 95 E85": F.OTHER,
    "Gasolina Renovable": F.OTHER,
    "Bioetanol": F.OTHER,
    "Biodiesel": F.OTHER,
}


def categorize(product: str) -> F | None:
    return FUELS.get(product)


def parse_fecha(value: object) -> date | None:
    try:
        return datetime.strptime(clean(value), "%d/%m/%Y %H:%M:%S").date()
    except ValueError:
        return None


def _in_spain(lat: float, lon: float) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


def resolve_coords(lat: float | None, lon: float | None) -> tuple[float, float] | None:
    """Coordinates inside Spain; a few rows have latitude and longitude swapped."""
    if lat is None or lon is None:
        return None
    if _in_spain(lat, lon):
        return lat, lon
    if _in_spain(lon, lat):
        return lon, lat
    return None


def build_dataset(data: dict[str, Any]) -> Dataset:
    if data.get("ResultadoConsulta", "OK") != "OK":
        raise ValueError(f"source error: {data.get('ResultadoConsulta')!r}")
    stations: list[Station] = []
    for s in data.get("ListaEESSPrecio") or []:
        coords = resolve_coords(number(s.get("Latitud")), number(s.get("Longitud (WGS84)")))
        if coords is None:
            continue
        prices: list[Price] = []
        for key, value in s.items():
            if not key.startswith(PRICE_PREFIX) or not value:
                continue
            product = key.removeprefix(PRICE_PREFIX)
            category = categorize(product)
            price = valid_price(value)
            if category is None or price is None:
                continue
            prices.append(Price(category=category, product=product, price=price))
        if not prices:
            continue
        lat, lon = coords
        stations.append(Station(
            id=clean(s.get("IDEESS")),
            name=clean(s.get("Rótulo")),
            address=clean(s.get("Dirección")),
            city=" ".join(filter(None, [clean(s.get("C.P.")), clean(s.get("Localidad"))])),
            province=clean(s.get("Provincia")),
            lat=lat,
            lon=lon,
            prices=prices,
        ))
    return Dataset(stations=stations, data_date=parse_fecha(data.get("Fecha")), fetched_at=datetime.now(UTC))

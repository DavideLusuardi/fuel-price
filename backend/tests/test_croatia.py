import gzip
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from fuelprice.core.models import FuelCategory as F
from fuelprice.plugins.croatia import DATA_URL, CroatiaPlugin
from fuelprice.plugins.croatia.parser import build_dataset, categorize, parse_coord, resolve_lat_lon

FIX = Path(__file__).parent / "fixtures"


def _data():
    return json.loads((FIX / "hr_data.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("raw", "expected"), [
    ("45.684651", 45.684651),
    (" 13.9 ", 13.9),
    ("45° 39.4112' N", 45 + 39.4112 / 60),
    ("15° 31.2440' E", 15 + 31.2440 / 60),
    ("45°39'30\" N", 45 + 39 / 60 + 30 / 3600),
    ("", None),
    (None, None),
    ("https://goo.gl/maps/TX3QLUNrgF5JrBUS8", None),
])
def test_parse_coord(raw, expected):
    got = parse_coord(raw)
    assert got == pytest.approx(expected) if expected is not None else got is None


def test_resolve_lat_lon_by_range():
    assert resolve_lat_lon(45.68, 15.74) == (45.68, 15.74)
    assert resolve_lat_lon(15.74, 45.68) == (45.68, 15.74)  # swapped fields
    assert resolve_lat_lon(47.71851, 15.89062) is None  # outside Croatia
    assert resolve_lat_lon(None, 15.0) is None


@pytest.mark.parametrize(("vrsta", "name", "expected"), [
    (1, "EUROSUPER 95 CLASS PLUS", F.PETROL),
    (2, "Eurosuper BS 95", F.PETROL),
    (1, "EUROSUPER 95 CLASS PLUS PREMIUM", F.PREMIUM_PETROL),
    (5, "Q MAX EUROSUPER 100", F.PREMIUM_PETROL),
    (6, "Eurosuper 100 BS", F.PREMIUM_PETROL),
    (7, "EURODIZEL CLASS PLUS", F.DIESEL),
    (8, "EURODIESEL BS", F.DIESEL),
    (7, "EVO Eurodiesel BS Premium", F.PREMIUM_DIESEL),
    (7, "SHELL V-POWER EURODIESEL", F.PREMIUM_DIESEL),
    (7, "EURODIESEL G-POWER", F.PREMIUM_DIESEL),
    (7, None, F.DIESEL),
    (9, "AUTOPLIN", F.LPG),
    (26, "SPP", F.CNG),
    (10, "LOŽ ULJE", None),  # heating oil
    (11, "PLAVI DIZEL", None),  # agricultural blue diesel
    (13, "Biodizel", None),
    (21, "PLINSKA BOCA 10KG", None),  # bottled LPG
    (23, "DC Fast Charging", None),
    (999, "unknown", None),
])
def test_categorize(vrsta, name, expected):
    assert categorize(vrsta, name) is expected


def test_build_dataset():
    ds = build_dataset(_data(), date(2026, 11, 10))
    by_id = {s.id: s for s in ds.stations}
    # 804: no coords; 1245: URL coords; 1033: DMS coords but kuna-era prices
    assert set(by_id) == {"1223", "1431", "1425", "913", "933"}
    assert ds.data_date == date(2026, 11, 10)

    klinca = by_id["1223"]  # swapped coordinate fields
    assert (klinca.lat, klinca.lon) == (45.684651, 15.748905)
    assert klinca.brand == "TOMICA BENZ d.o.o." and klinca.city == "KLINČA SELA"
    assert sorted((p.category, p.product, p.price) for p in klinca.prices) == sorted([
        (F.DIESEL, "EURODIZEL B7", 1.38),
        (F.PETROL, "EUROSUPER 95", 1.43),
        (F.LPG, "AUTOPLIN", 0.79),
        (F.DIESEL, "EURODIZEL B7 ADD", 1.44),
    ])  # blue diesel and gas cylinders dropped
    assert all(p.self_service is None and p.updated_at is None for p in klinca.prices)

    mokrice = by_id["1431"]  # fields in the documented order
    assert (mokrice.lat, mokrice.lon) == (46.00406, 15.880329)

    slano = {p.product: p.category for p in by_id["1425"].prices}
    assert slano["EVO Eurodiesel BS Premium"] is F.PREMIUM_DIESEL
    assert slano["EVO Eurosuper 100+ BS Premium"] is F.PREMIUM_PETROL

    zminj = {p.product: p.price for p in by_id["913"].prices}
    assert "ULJE ZA LOŽENJE EL EURO" not in zminj  # 0.0 heating oil

    pazin = {p.product for p in by_id["933"].prices}
    assert "" not in pazin


@respx.mock
async def test_fetch_gzip_and_last_modified():
    body = gzip.compress((FIX / "hr_data.json").read_bytes())
    respx.get(DATA_URL).respond(200, content=body, headers={"Last-Modified": "Tue, 10 Nov 2026 12:40:27 GMT"})
    async with httpx.AsyncClient() as client:
        ds = await CroatiaPlugin().fetch(client)
    assert ds.data_date == date(2026, 11, 10)
    assert len(ds.stations) == 5


@respx.mock
async def test_fetch_plain_json_without_last_modified():
    respx.get(DATA_URL).respond(200, content=(FIX / "hr_data.json").read_bytes())
    async with httpx.AsyncClient() as client:
        ds = await CroatiaPlugin().fetch(client)
    assert len(ds.stations) == 5

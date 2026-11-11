import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

import fuelprice.plugins.spain as spain
from fuelprice.core.models import FuelCategory as F
from fuelprice.plugins.spain import DATA_URL, SpainPlugin
from fuelprice.plugins.spain.parser import build_dataset, categorize, parse_fecha, resolve_coords

FIX = Path(__file__).parent / "fixtures"


def _raw() -> bytes:
    return (FIX / "es_estaciones.json").read_bytes()


def _data():
    return json.loads(_raw())


@pytest.mark.parametrize(("product", "expected"), [
    ("Gasolina 95 E5", F.PETROL),
    ("Gasolina 95 E10", F.PETROL),
    ("Gasolina 95 E5 Premium", F.PETROL),  # octane decides, not the brand name
    ("Gasolina 98 E5", F.PREMIUM_PETROL),
    ("Gasoleo A", F.DIESEL),
    ("Gasoleo Premium", F.PREMIUM_DIESEL),
    ("Diésel Renovable", F.HVO),
    ("Gases licuados del petróleo", F.LPG),
    ("Biogas Natural Comprimido", F.CNG),
    ("Gas Natural Licuado", F.LNG),
    ("Gasolina 95 E85", F.OTHER),
    ("Gasoleo B", None),  # agricultural
    ("Adblue", None),
    ("Hidrogeno", None),
])
def test_categorize(product, expected):
    assert categorize(product) is expected


def test_parse_fecha():
    assert parse_fecha("11/11/2026 11:03:32") == date(2026, 11, 11)
    assert parse_fecha("") is None
    assert parse_fecha(None) is None


def test_resolve_coords():
    assert resolve_coords(39.2, -1.5) == (39.2, -1.5)
    assert resolve_coords(-8.659472, 42.037472) == (42.037472, -8.659472)  # swapped
    assert resolve_coords(28.1, -15.4) == (28.1, -15.4)  # Canary Islands
    assert resolve_coords(0.0, 0.0) is None
    assert resolve_coords(None, 1.0) is None


def test_build_dataset():
    ds = build_dataset(_data())
    by_id = {s.id: s for s in ds.stations}
    # 11988: 0,0 coordinates; 11072: only agricultural diesel
    assert set(by_id) == {"4375", "16268", "10133", "1784", "5195", "13829", "14612", "7901", "3434"}
    assert ds.data_date == date(2026, 11, 11)

    abengibre = by_id["4375"]
    assert (abengibre.lat, abengibre.lon) == (39.211417, -1.539167)
    assert abengibre.name == "Nº 10.935" and abengibre.brand == ""
    assert abengibre.address == "AVENIDA CASTILLA LA MANCHA, 26"
    assert abengibre.city == "02250 ABENGIBRE" and abengibre.province == "ALBACETE"
    assert sorted((p.category, p.product, p.price) for p in abengibre.prices) == sorted([
        (F.DIESEL, "Gasoleo A", 1.799),
        (F.PETROL, "Gasolina 95 E5", 1.649),
    ])  # Gasoleo B dropped
    assert all(p.updated_at is None and p.self_service is None for p in abengibre.prices)

    tui = by_id["16268"]  # swapped coordinate fields, AdBlue dropped
    assert (tui.lat, tui.lon) == (42.037472, -8.659472)
    assert {p.product for p in tui.prices} == {"Gasoleo A", "Gasoleo Premium", "Gasolina 95 E5"}

    hydrogen = {p.product for p in by_id["10133"].prices}
    assert "Hidrogeno" not in hydrogen and "Diésel Renovable" in hydrogen

    rich = {p.product: p.category for p in by_id["1784"].prices}
    assert rich["Gasolina 95 E5 Premium"] is F.PETROL
    assert rich["Gasoleo Premium"] is F.PREMIUM_DIESEL

    gas = {(p.product, p.category) for p in by_id["13829"].prices}
    assert gas == {
        ("Gas Natural Comprimido", F.CNG), ("Biogas Natural Comprimido", F.CNG),
        ("Gas Natural Licuado", F.LNG), ("Biogas Natural Licuado", F.LNG),
    }
    assert by_id["7901"].lat < 29  # Canary Islands


def test_build_dataset_source_error():
    with pytest.raises(ValueError):
        build_dataset({"ResultadoConsulta": "ERROR", "ListaEESSPrecio": []})


@respx.mock
async def test_fetch_with_bom():
    respx.get(DATA_URL).respond(200, content=b"\xef\xbb\xbf" + _raw())
    async with httpx.AsyncClient() as client:
        ds = await SpainPlugin().fetch(client)
    assert len(ds.stations) == 9


@respx.mock
async def test_fetch_retries_once(monkeypatch):
    monkeypatch.setattr(spain, "RETRY_DELAY", 0)
    route = respx.get(DATA_URL)
    route.side_effect = [httpx.ReadError("connection reset"), httpx.Response(200, content=_raw())]
    async with httpx.AsyncClient() as client:
        ds = await SpainPlugin().fetch(client)
    assert route.call_count == 2 and len(ds.stations) == 9


@respx.mock
async def test_fetch_gives_up_after_two_failures(monkeypatch):
    monkeypatch.setattr(spain, "RETRY_DELAY", 0)
    route = respx.get(DATA_URL)
    route.side_effect = httpx.ReadError("connection reset")
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ReadError):
            await SpainPlugin().fetch(client)
    assert route.call_count == 2


@respx.mock
async def test_fetch_http_error_is_not_retried():
    route = respx.get(DATA_URL).respond(500)
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await SpainPlugin().fetch(client)
    assert route.call_count == 1

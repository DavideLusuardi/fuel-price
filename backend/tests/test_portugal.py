import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
import respx

import fuelprice.plugins.portugal as pt
from fuelprice.core.models import FuelCategory as F
from fuelprice.plugins.portugal import SEARCH_URL, PortugalPlugin, search_fuel
from fuelprice.plugins.portugal.parser import FUELS, LISBON, build_dataset, parse_date, parse_price

FIX = Path(__file__).parent / "fixtures"


def _results() -> dict[int, list[dict]]:
    raw = json.loads((FIX / "pt_postos.json").read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def _respond(request: httpx.Request) -> httpx.Response:
    rows = _results().get(int(request.url.params["idsTiposComb"]), [])
    return httpx.Response(200, json={"status": True, "mensagem": "sucesso", "resultado": rows})


@pytest.mark.parametrize(("raw", "expected"), [
    ("2,246 €", 2.246),
    ("1,109 €", 1.109),
    ("0,001 €", None),
    ("", None),
    (None, None),
])
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_parse_date():
    assert parse_date("2026-11-11 04:45") == datetime(2026, 11, 11, 4, 45, tzinfo=LISBON)
    assert parse_date("11/11/2026") is None


def test_build_dataset():
    ds = build_dataset(_results())
    by_id = {s.id: s for s in ds.stations}
    # 999001: placeholder price; 999002: no coordinates
    assert set(by_id) == {"65653", "94509", "93221", "65156", "95261", "73796"}
    assert ds.data_date == date(2026, 11, 11)

    sines = by_id["65653"]
    assert sines.name == "GALP Sines" and sines.brand == "GALP" and sines.province == "Setúbal"
    assert sorted((p.category, p.product, p.price) for p in sines.prices) == sorted([
        (F.CNG, "GNC (gás natural comprimido) - €/kg", 2.577),
        (F.LNG, "GNL (gás natural liquefeito) - €/kg", 3.239),
        (F.PREMIUM_DIESEL, "Gasóleo especial", 2.296),
        (F.PETROL, "Gasolina simples 95", 1.989),
        (F.DIESEL, "Gasóleo simples", 2.246),
        (F.PETROL, "Gasolina especial 95", 2.039),
        (F.LPG, "GPL Auto", 1.109),
    ])
    assert all(p.updated_at == datetime(2026, 11, 11, 4, 45, tzinfo=LISBON) for p in sines.prices)
    assert all(p.self_service is None for p in sines.prices)

    motorway = {p.product: p.category for p in by_id["94509"].prices}
    assert motorway["Gasolina especial 98"] is F.PREMIUM_PETROL
    assert {p.product: p.category for p in by_id["95261"].prices}["Biodiesel B15"] is F.OTHER
    assert by_id["73796"].brand == ""  # "Genérico"
    assert {p.product: p.category for p in by_id["73796"].prices}["Gasolina 98"] is F.PREMIUM_PETROL


def test_unknown_fuel_ids_are_ignored():
    rows = _results()[2101]
    assert build_dataset({2150: rows}).stations == []  # coloured diesel


@respx.mock
async def test_fetch_requests_every_fuel_once():
    route = respx.get(SEARCH_URL).mock(side_effect=_respond)
    async with httpx.AsyncClient() as client:
        ds = await PortugalPlugin().fetch(client)
    assert route.call_count == len(FUELS)
    assert {int(c.request.url.params["idsTiposComb"]) for c in route.calls} == set(FUELS)
    assert len(ds.stations) == 6


@respx.mock
async def test_search_follows_pages(monkeypatch):
    monkeypatch.setattr(pt, "PAGE_SIZE", 2)
    rows = [{"Id": i, "Quantidade": 3} for i in range(3)]

    def page(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params["pagina"])
        return httpx.Response(200, json={"status": True, "resultado": rows[(n - 1) * 2:n * 2]})

    route = respx.get(SEARCH_URL).mock(side_effect=page)
    async with httpx.AsyncClient() as client:
        got = await search_fuel(client, 2101)
    assert [r["Id"] for r in got] == [0, 1, 2] and route.call_count == 2


@respx.mock
async def test_fetch_source_error_raises():
    respx.get(SEARCH_URL).respond(200, json={"status": False, "mensagem": "erro", "resultado": None})
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            await PortugalPlugin().fetch(client)


@respx.mock
async def test_fetch_http_error_raises():
    respx.get(SEARCH_URL).respond(503)
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await PortugalPlugin().fetch(client)

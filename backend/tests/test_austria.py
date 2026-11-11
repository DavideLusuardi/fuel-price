import json
from pathlib import Path

import httpx
import pytest
import respx

from fuelprice.core.models import FuelCategory as F
from fuelprice.plugins.austria import REGIONS_URL, SEARCH_URL, AustriaPlugin
from fuelprice.plugins.austria.parser import FUELS, build_dataset, districts

FIX = Path(__file__).parent / "fixtures"


def _regions() -> list[dict]:
    return json.loads((FIX / "at_regions.json").read_text(encoding="utf-8"))


def _search() -> dict[str, list[dict]]:
    return json.loads((FIX / "at_search.json").read_text(encoding="utf-8"))


def _results() -> list[tuple[str, str, list[dict]]]:
    states = districts(_regions())
    out = []
    for key, rows in _search().items():
        code, fuel = key.split("/")
        out.append((states[int(code)], fuel, rows))
    return out


def _respond(request: httpx.Request) -> httpx.Response:
    p = request.url.params
    return httpx.Response(200, json=_search().get(f"{p['code']}/{p['fuelType']}", []))


def test_districts():
    assert districts(_regions()) == {101: "Burgenland", 401: "Oberösterreich", 901: "Wien"}


def test_build_dataset():
    ds = build_dataset(_results())
    by_id = {s.id: s for s in ds.stations}
    # 999001: placeholder price, 999002: no coordinates, 999003: no price,
    # 45247: test entry at (1.11, 1.11)
    assert set(by_id) == {"1474414", "1354680", "1214419", "1471167", "449828", "42886", "35567", "284"}
    assert ds.data_date is None

    disk = by_id["1474414"]
    assert disk.name == "Diskont Tankstelle" and disk.brand == ""
    assert disk.city == "7000 Eisenstadt" and disk.province == "Burgenland"
    assert (disk.lat, disk.lon) == (47.825, 16.5319)
    assert [(p.category, p.product, p.price) for p in disk.prices] == [(F.PETROL, "Super 95", 1.639)]
    assert all(p.updated_at is None and p.self_service is None for p in disk.prices)

    # found in both the SUP and the DIE search
    assert {p.category for p in by_id["1214419"].prices} == {F.PETROL, F.DIESEL}
    assert [(p.category, p.price) for p in by_id["284"].prices] == [(F.CNG, 1.799)]
    assert by_id["35567"].province == "Wien"


def test_duplicate_search_rows_keep_one_price():
    rows = _search()["101/SUP"]
    ds = build_dataset([("Burgenland", "SUP", rows), ("Wien", "SUP", rows)])
    assert all(len(s.prices) == 1 and s.province == "Burgenland" for s in ds.stations)


def test_unknown_fuel_is_ignored():
    assert build_dataset([("Burgenland", "SUP_PLUS", _search()["101/SUP"])]).stations == []


@respx.mock
async def test_fetch_searches_every_district_and_fuel():
    respx.get(REGIONS_URL).respond(200, json=_regions())
    route = respx.get(SEARCH_URL).mock(side_effect=_respond)
    async with httpx.AsyncClient() as client:
        ds = await AustriaPlugin().fetch(client)
    assert route.call_count == 3 * len(FUELS)
    assert {(c.request.url.params["code"], c.request.url.params["fuelType"]) for c in route.calls} == {
        (c, f) for c in ("101", "401", "901") for f in FUELS
    }
    assert all(c.request.url.params["includeClosed"] == "true" for c in route.calls)
    assert len(ds.stations) == 8


@respx.mock
async def test_fetch_without_districts_raises():
    respx.get(REGIONS_URL).respond(200, json=[])
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            await AustriaPlugin().fetch(client)


@respx.mock
async def test_fetch_http_error_raises():
    respx.get(REGIONS_URL).respond(200, json=_regions())
    respx.get(SEARCH_URL).respond(503)
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await AustriaPlugin().fetch(client)

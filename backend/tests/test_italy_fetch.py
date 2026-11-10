import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx

from fuelprice.core.models import FuelCategory as F
from fuelprice.plugins.italy import AREA_URL, CSV_BASE_URL, REGIONS_URL, ItalyPlugin
from fuelprice.plugins.italy.osservaprezzi import PriceDateEstimator, parse_area_results, split_address

FIX = Path(__file__).parent / "fixtures"
STATIONS_URL = f"{CSV_BASE_URL}/anagrafica_impianti_attivi.csv"
PRICES_URL = f"{CSV_BASE_URL}/prezzo_alle_8.csv"


def _json(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _api_results():
    return _json("it_api_region_19.json")["results"] + _json("it_api_region_14.json")["results"]


@pytest.fixture
def plugin():
    p = ItalyPlugin()
    p.sleeps = []

    async def fake_sleep(s):
        p.sleeps.append(s)

    p.sleep = fake_sleep
    return p


def _mock_api(area_side_effect=None):
    respx.get(REGIONS_URL).respond(200, json=_json("it_api_regions.json"))

    def area(request):
        region = json.loads(request.content)["region"]
        return httpx.Response(200, json=_json(f"it_api_region_{region}.json"))

    return respx.post(AREA_URL).mock(side_effect=area_side_effect or area)


def _mock_csv(base=CSV_BASE_URL):
    respx.get(f"{base}/anagrafica_impianti_attivi.csv").respond(200, content=(FIX / "anagrafica.csv").read_bytes())
    respx.get(f"{base}/prezzo_alle_8.csv").respond(200, content=(FIX / "prezzi.csv").read_bytes())


# -- Osservaprezzi parsing -----------------------------------------------------------

@pytest.mark.parametrize(("raw", "expected"), [
    ("BRESCIA 21 25039 - TRAVAGLIATO BS", ("BRESCIA 21 25039", "TRAVAGLIATO", "BS")),
    ("VIA FAUSTA 207 30013 - CAVALLINO-TREPORTI VE", ("VIA FAUSTA 207 30013", "CAVALLINO-TREPORTI", "VE")),
    ("Autostrada A3, Km. 274+653, dir. Sud - - - MARZI CS", ("Autostrada A3, Km. 274+653, dir. Sud", "MARZI", "CS")),
    ("VIA SENZA CITTA", ("VIA SENZA CITTA", "", "")),
    (None, ("", "", "")),
])
def test_split_address(raw, expected):
    assert split_address(raw) == expected


def test_parse_area_results():
    stations = {s.id: s for s in parse_area_results(_api_results())}
    assert set(stations) == {"54120", "55135", "31097", "61594", "24827"}  # 58314 has 0,0 coordinates
    s = stations["54120"]
    assert (s.name, s.brand, s.address, s.city, s.province) == (
        "IPERPETROLI3", "Pompe Bianche", "BRESCIA 21 25039", "TRAVAGLIATO", "BS")
    assert [(p.category, p.product, p.price, p.self_service) for p in s.prices] == [
        (F.PETROL, "Benzina", 1.979, True), (F.DIESEL, "Gasolio", 2.219, True)]
    assert stations["31097"].brand == "AF Petroli"
    assert {p.category for p in stations["31097"].prices} >= {F.LPG, F.PREMIUM_DIESEL}


def test_price_dates_are_estimated_from_ids():
    stations = {s.id: s for s in parse_area_results(_api_results())}
    station_date = datetime.fromisoformat("2026-11-10T14:19:10+01:00")
    gpl = next(p for p in stations["55135"].prices if p.product == "GPL")  # id far older than any station update
    fresh = next(p for p in stations["55135"].prices if p.product == "Benzina")
    oldest_station = datetime.fromisoformat("2026-09-15T21:54:11+01:00")
    assert gpl.updated_at == oldest_station  # lower bound of its age -> filtered by the 7-day rule
    assert oldest_station < fresh.updated_at <= station_date
    # a station that last reported in September keeps September dates
    assert all(p.updated_at == oldest_station for p in stations["61594"].prices)


def test_estimator_without_data():
    est = PriceDateEstimator([])
    when = datetime.fromisoformat("2026-11-10T10:00:00+01:00")
    assert est.estimate(123, when) == when
    assert est.oldest is None


# -- fetch: API first, CSV fallback ------------------------------------------------------

@respx.mock
async def test_fetch_uses_api_region_by_region(plugin):
    area = _mock_api()
    async with httpx.AsyncClient() as client:
        ds = await plugin.fetch(client)
    assert len(ds.stations) == 5
    assert [json.loads(c.request.content) for c in area.calls] == [{"region": r["id"]} for r in _json("it_api_regions.json")["results"]]
    assert plugin.sleeps == [1.5]  # pause between regions, never in parallel
    assert ds.data_date is not None


@respx.mock
async def test_fetch_retries_when_rate_limited(plugin):
    responses = iter([httpx.Response(429), httpx.Response(429)])

    def area(request):
        try:
            return next(responses)
        except StopIteration:
            region = json.loads(request.content)["region"]
            return httpx.Response(200, json=_json(f"it_api_region_{region}.json"))

    _mock_api(area)
    async with httpx.AsyncClient() as client:
        ds = await plugin.fetch(client)
    assert len(ds.stations) == 5
    assert plugin.sleeps[:2] == [5, 15]


@respx.mock
async def test_fetch_falls_back_to_csv_when_api_fails(plugin):
    respx.get(REGIONS_URL).respond(503)
    _mock_csv()
    async with httpx.AsyncClient() as client:
        ds = await plugin.fetch(client)
    assert {s.id for s in ds.stations} == {"59183", "63381", "40820", "59690"}  # CSV fixture
    assert ds.stations[0].operator == "ENIMOOV S.P.A."


@respx.mock
async def test_fetch_falls_back_to_csv_when_api_keeps_rate_limiting(plugin):
    _mock_api(lambda request: httpx.Response(429))
    _mock_csv()
    async with httpx.AsyncClient() as client:
        ds = await plugin.fetch(client)
    assert len(ds.stations) == 4


@respx.mock
async def test_csv_base_url_can_point_to_a_proxy(plugin, monkeypatch):
    monkeypatch.setenv("FUELPRICE_IT_CSV_BASE_URL", "https://proxy.example.org/mimit/")
    respx.get(REGIONS_URL).respond(503)
    _mock_csv("https://proxy.example.org/mimit")
    async with httpx.AsyncClient() as client:
        ds = await plugin.fetch(client)
    assert len(ds.stations) == 4


@respx.mock
async def test_csv_decodes_latin1(plugin):
    stations = (FIX / "anagrafica.csv").read_text(encoding="utf-8").encode("latin-1")
    respx.get(STATIONS_URL).respond(200, content=stations)
    respx.get(PRICES_URL).respond(200, content=(FIX / "prezzi.csv").read_bytes())
    async with httpx.AsyncClient() as client:
        ds = await plugin.fetch_csv(client)
    assert next(s for s in ds.stations if s.id == "59690").city == "CANICATTÌ"


@respx.mock
async def test_fetch_raises_when_both_sources_fail(plugin):
    respx.get(REGIONS_URL).respond(503)
    respx.get(STATIONS_URL).respond(500)
    respx.get(PRICES_URL).respond(200, content=b"")
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await plugin.fetch(client)

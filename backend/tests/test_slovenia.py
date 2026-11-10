import json
from pathlib import Path

import httpx
import respx

from fuelprice.core.models import FuelCategory as F
from fuelprice.plugins.slovenia import FRANCHISE_URL, SEARCH_URL, SloveniaPlugin
from fuelprice.plugins.slovenia.parser import parse_franchises, parse_stations

FIX = Path(__file__).parent / "fixtures"


def _json(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _results():
    return _json("si_search_page1.json")["results"] + _json("si_search_page2.json")["results"]


def test_parse_franchises():
    fr = parse_franchises(_json("si_franchise.json"))
    assert fr[5].startswith("Shell") or "SHELL" in fr[5].upper()


def test_parse_stations_maps_and_filters():
    stations = {s.id: s for s in parse_stations(_results(), parse_franchises(_json("si_franchise.json")))}
    # KOEL-only (heating oil) and coordinate-less stations are dropped
    assert set(stations) == {"2258", "2259", "2260", "771"}
    koper = stations["2258"]
    assert koper.name == "SHELL KOPER"
    assert koper.address == "SERMIN 7C" and koper.city == "6000"
    assert (koper.lat, koper.lon) == (45.552486, 13.762092)
    # the 0.001 placeholder for 95 is dropped
    assert [(p.category, p.product, p.price) for p in koper.prices] == [(F.DIESEL, "Dizel", 1.848)]
    assert koper.prices[0].self_service is None and koper.prices[0].updated_at is None

    brezice = stations["771"]
    cats = {p.category: p.price for p in brezice.prices}
    assert cats == {F.PETROL: 1.506, F.DIESEL: 1.848, F.PREMIUM_PETROL: 1.849, F.PREMIUM_DIESEL: 2.289}
    assert brezice.brand  # resolved from the franchise list


@respx.mock
async def test_fetch_walks_all_pages():
    respx.get(FRANCHISE_URL).respond(200, json=_json("si_franchise.json"))
    route = respx.get(SEARCH_URL)
    route.side_effect = lambda request: httpx.Response(
        200, json=_json(f"si_search_page{request.url.params.get('page', '1')}.json")
    )
    async with httpx.AsyncClient() as client:
        ds = await SloveniaPlugin().fetch(client)
    assert {s.id for s in ds.stations} == {"2258", "2259", "2260", "771"}
    assert ds.data_date is not None
    assert route.call_count == 2

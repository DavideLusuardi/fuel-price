import json
from pathlib import Path

import httpx
import pytest
import respx

from fuelprice.core.models import FuelCategory as F
from fuelprice.core.parsing import valid_price
from fuelprice.plugins.iceland import DATA_URL, IcelandPlugin
from fuelprice.plugins.iceland.parser import PRICE_RANGE_ISK, build_dataset

FIX = Path(__file__).parent / "fixtures"


def _raw() -> bytes:
    return (FIX / "is_gas.json").read_bytes()


def test_valid_price_with_currency_range():
    assert valid_price(256.3) is None  # outside the euro range
    assert valid_price(256.3, PRICE_RANGE_ISK) == 256.3
    assert valid_price(1.849, PRICE_RANGE_ISK) is None
    assert valid_price("1,849") == 1.849  # euro default unchanged


def test_build_dataset():
    ds = build_dataset(json.loads(_raw()))
    by_id = {s.id: s for s in ds.stations}
    # test_badprice: only placeholder/euro-like prices; test_nogeo: no coordinates
    assert set(by_id) == {"ao_000", "n1_000", "or_000", "ob_000", "ol_000", "co_000", "test_nodiesel"}
    assert ds.data_date is None

    akureyri = by_id["ao_000"]
    assert (akureyri.lat, akureyri.lon) == (65.69913, -18.135231)
    assert akureyri.name == "Baldursnes Akureyri" and akureyri.brand == "Atlantsolía"
    assert sorted((p.category, p.product, p.price) for p in akureyri.prices) == sorted([
        (F.PETROL, "Bensín 95", 256.3),
        (F.DIESEL, "Dísel", 314.2),
    ])
    assert all(p.updated_at is None and p.self_service is None for p in akureyri.prices)

    n1 = {p.product: p.price for p in by_id["n1_000"].prices}
    assert n1 == {"Bensín 95": 286.4, "Dísel": 340.5}  # loyalty discounts skipped

    assert [p.product for p in by_id["test_nodiesel"].prices] == ["Bensín 95"]


@respx.mock
async def test_fetch():
    respx.get(DATA_URL).respond(200, content=_raw(), headers={"Content-Type": "text/plain; charset=utf-8"})
    async with httpx.AsyncClient() as client:
        ds = await IcelandPlugin().fetch(client)
    assert len(ds.stations) == 7


@respx.mock
async def test_fetch_error_raises():
    respx.get(DATA_URL).respond(404)
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await IcelandPlugin().fetch(client)

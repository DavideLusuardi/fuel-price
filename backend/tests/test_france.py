import io
import zipfile
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from fuelprice.core.models import FuelCategory as F
from fuelprice.plugins.france import DATA_URL, FrancePlugin, unpack
from fuelprice.plugins.france.parser import PARIS, build_dataset, categorize, parse_maj

FIX = Path(__file__).parent / "fixtures"


def _xml() -> bytes:
    return (FIX / "fr_instantane.xml").read_bytes()


def _zip(xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PrixCarburants_instantane.xml", xml)
    return buf.getvalue()


@pytest.mark.parametrize(("name", "expected"), [
    ("Gazole", F.DIESEL),
    ("SP95", F.PETROL),
    ("E10", F.PETROL),
    ("SP98", F.PREMIUM_PETROL),
    ("GPLc", F.LPG),
    ("E85", F.OTHER),
    ("Hydrogène", None),
    ("", None),
])
def test_categorize(name, expected):
    assert categorize(name) is expected


def test_parse_maj():
    assert parse_maj("2026-11-11 01:17:00") == datetime(2026, 11, 11, 1, 17, tzinfo=PARIS)
    assert parse_maj("") is None
    assert parse_maj("11/11/2026") is None


def test_build_dataset():
    ds = build_dataset(_xml())
    by_id = {s.id: s for s in ds.stations}
    # 69700002: no prices; 99999002: no coordinates
    assert set(by_id) == {"38230003", "33114001", "18200011", "20137007", "74800001", "99999001"}
    assert ds.data_date == date(2026, 11, 11)

    full = by_id["38230003"]
    assert (full.lat, full.lon) == (45.745, 5.183)
    assert full.name == "Tignieu-Jameyzieu" and full.city == "38230 Tignieu-Jameyzieu"
    assert full.address == "Rue des Ardennes" and full.brand == ""
    assert sorted((p.category, p.product, p.price) for p in full.prices) == sorted([
        (F.DIESEL, "Gazole", 2.089),
        (F.PETROL, "SP95", 2.071),
        (F.OTHER, "E85", 0.858),
        (F.LPG, "GPLc", 0.998),
        (F.PETROL, "E10", 1.948),
        (F.PREMIUM_PETROL, "SP98", 2.079),
    ])
    assert all(p.self_service is None for p in full.prices)
    assert all(p.updated_at == datetime(2026, 11, 11, 1, 17, tzinfo=PARIS) for p in full.prices)

    assert by_id["18200011"].name == "FARGE ALLICHAMPS (autoroute)"
    assert by_id["33114001"].address == "Avenue du Médoc ZAC Eyrialis"  # ISO-8859-1 decoded
    assert (by_id["33114001"].lat, by_id["33114001"].lon) == (44.623, -0.787)  # west of Greenwich
    assert by_id["20137007"].lat == pytest.approx(41.602)  # Corsica

    fake = by_id["99999001"]  # placeholder 0.001 and unknown product dropped, comma decimal parsed
    assert [(p.product, p.price) for p in fake.prices] == [("E10", 1.899)]


def test_unpack_zip_and_plain():
    xml = _xml()
    assert unpack(_zip(xml)) == xml
    assert unpack(xml) == xml
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "nothing")
    with pytest.raises(ValueError):
        unpack(buf.getvalue())


@respx.mock
async def test_fetch():
    respx.get(DATA_URL).respond(200, content=_zip(_xml()), headers={"Content-Type": "application/zip"})
    async with httpx.AsyncClient() as client:
        ds = await FrancePlugin().fetch(client)
    assert len(ds.stations) == 6


@respx.mock
async def test_fetch_error_raises():
    respx.get(DATA_URL).respond(503)
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await FrancePlugin().fetch(client)

from pathlib import Path

import httpx
import respx

from fuelprice.plugins.italy import PRICES_URL, STATIONS_URL, ItalyPlugin

FIX = Path(__file__).parent / "fixtures"


@respx.mock
async def test_fetch_downloads_and_parses():
    respx.get(STATIONS_URL).respond(200, content=(FIX / "anagrafica.csv").read_bytes())
    respx.get(PRICES_URL).respond(200, content=(FIX / "prezzi.csv").read_bytes())
    async with httpx.AsyncClient() as client:
        ds = await ItalyPlugin().fetch(client)
    assert {s.id for s in ds.stations} == {"59183", "63381", "40820", "59690"}


@respx.mock
async def test_fetch_decodes_latin1():
    stations = (FIX / "anagrafica.csv").read_text(encoding="utf-8").encode("latin-1")
    respx.get(STATIONS_URL).respond(200, content=stations)
    respx.get(PRICES_URL).respond(200, content=(FIX / "prezzi.csv").read_bytes())
    async with httpx.AsyncClient() as client:
        ds = await ItalyPlugin().fetch(client)
    assert next(s for s in ds.stations if s.id == "59690").city == "CANICATTÌ"


@respx.mock
async def test_fetch_raises_on_http_error():
    respx.get(STATIONS_URL).respond(500)
    respx.get(PRICES_URL).respond(200, content=b"")
    async with httpx.AsyncClient() as client:
        try:
            await ItalyPlugin().fetch(client)
        except httpx.HTTPStatusError:
            return
    raise AssertionError("expected HTTPStatusError")

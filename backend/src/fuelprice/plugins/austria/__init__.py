"""Austria: E-Control "Spritpreisrechner" API (api.e-control.at/sprit/1.0).

Stations must report every price change to E-Control, but the public API only shows
the cheapest stations: a search by political district returns at most five stations
with a price per fuel type. The build searches all 117 districts for each fuel (about
350 small requests) and merges the results, so Austria shows the cheapest stations of
every district, not every station. There are no brands and no price timestamps.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.austria.parser import FUELS, build_dataset, districts

BASE_URL = "https://api.e-control.at/sprit/1.0"
REGIONS_URL = f"{BASE_URL}/regions"
SEARCH_URL = f"{BASE_URL}/search/gas-stations/by-region"
MAX_CONCURRENCY = 4


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> Any:
    resp = await client.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


class AustriaPlugin(CountryPlugin):
    code = "at"
    name = "Österreich"
    currency = "EUR"
    center = (47.6, 13.3)
    zoom = 7
    has_service_modes = False

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        regions = districts(await _get_json(client, REGIONS_URL, {"includeCities": "false"}))
        if not regions:
            raise ValueError("E-Control returned no districts")
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        async def search(code: int, fuel: str) -> tuple[str, str, list[dict[str, Any]]]:
            async with sem:
                rows = await _get_json(client, SEARCH_URL, {
                    "code": code, "type": "PB", "fuelType": fuel, "includeClosed": "true",
                })
            return regions[code], fuel, rows or []

        results = await asyncio.gather(*(search(c, f) for c in regions for f in FUELS))
        return await asyncio.to_thread(build_dataset, results)

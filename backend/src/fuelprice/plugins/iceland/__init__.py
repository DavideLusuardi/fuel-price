"""Iceland: gasvaktin (github.com/gasvaktin/gasvaktin, MIT licence).

Iceland has no official price feed. gasvaktin scrapes the websites of every fuel
company (Atlantsolía, Costco, N1, Olís, ÓB, Orkan) several times a day and commits one
JSON file with all their stations. Only 95 petrol and diesel are listed, with no
per-price timestamps or self/attended distinction.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.iceland.parser import build_dataset

DATA_URL = "https://raw.githubusercontent.com/gasvaktin/gasvaktin/master/vaktin/gas.min.json"


class IcelandPlugin(CountryPlugin):
    code = "is"
    name = "Ísland"
    currency = "ISK"
    center = (64.9, -18.6)
    zoom = 6
    has_service_modes = False

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        resp = await client.get(DATA_URL, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        return await asyncio.to_thread(lambda: build_dataset(json.loads(resp.content)))

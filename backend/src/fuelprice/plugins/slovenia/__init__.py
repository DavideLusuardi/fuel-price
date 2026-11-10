"""Slovenia: goriva.si, the price portal of the Slovenian Ministry of Economy.

The search API is paginated (25 stations per page) and has no per-price timestamps
or self/attended distinction.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.slovenia.parser import parse_franchises, parse_stations

SEARCH_URL = "https://goriva.si/api/v1/search/"
FRANCHISE_URL = "https://goriva.si/api/v1/franchise/"
MAX_CONCURRENCY = 4


class SloveniaPlugin(CountryPlugin):
    code = "si"
    name = "Slovenija"
    currency = "EUR"
    center = (46.15, 14.99)
    zoom = 8
    has_service_modes = False

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        async def get(url: str, **params: Any) -> Any:
            async with sem:
                resp = await client.get(url, params=params, timeout=30)
                resp.raise_for_status()
                return resp.json()

        franchises_json, first = await asyncio.gather(get(FRANCHISE_URL), get(SEARCH_URL, page=1))
        results = list(first["results"])
        page_size = len(results)
        if page_size and first.get("next"):
            pages = math.ceil(int(first["count"]) / page_size)
            rest = await asyncio.gather(*(get(SEARCH_URL, page=n) for n in range(2, pages + 1)))
            for page in rest:
                results.extend(page["results"])

        return Dataset(
            stations=parse_stations(results, parse_franchises(franchises_json)),
            data_date=datetime.now(ZoneInfo("Europe/Ljubljana")).date(),
            fetched_at=datetime.now(UTC),
        )

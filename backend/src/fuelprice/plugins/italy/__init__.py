"""Italy: fuel prices from the Ministero delle Imprese e del Made in Italy (MIMIT).

Two official sources, tried in this order:

1. Osservaprezzi API (``carburanti.mise.gov.it``): live prices, reachable from
   cloud servers; per-price dates are estimated (see ``osservaprezzi.py``).
2. Open-data CSVs (``www.mimit.gov.it``): exact per-price dates, prices as of
   08:00. Only reachable from some networks (it refuses GitHub's servers).
   Set ``FUELPRICE_IT_CSV_BASE_URL`` to fetch the CSVs through a mirror or
   URL-rewriting proxy instead.

https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.italy.osservaprezzi import parse_area_results
from fuelprice.plugins.italy.parser import build_dataset

log = logging.getLogger(__name__)

API_URL = "https://carburanti.mise.gov.it/ospzApi"
REGIONS_URL = f"{API_URL}/registry/region"
AREA_URL = f"{API_URL}/search/area"
# The API answers "429 Too Many Requests" to parallel requests: go one region at a time.
REQUEST_PAUSE_S = 1.5
RETRY_DELAYS_S = (5, 15, 30)

CSV_BASE_URL = "https://www.mimit.gov.it/images/exportCSV"
CSV_FILES = ("anagrafica_impianti_attivi.csv", "prezzo_alle_8.csv")

ROME = ZoneInfo("Europe/Rome")


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("latin-1")


class ItalyPlugin(CountryPlugin):
    code = "it"
    name = "Italia"
    currency = "EUR"
    center = (42.5, 12.5)
    zoom = 6
    has_service_modes = True

    sleep = staticmethod(asyncio.sleep)  # replaced in tests

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        try:
            return await self.fetch_api(client)
        except Exception as exc:
            log.warning("[it] Osservaprezzi API failed (%s: %s), falling back to the CSV files",
                        type(exc).__name__, exc)
        return await self.fetch_csv(client)

    # -- primary: Osservaprezzi API ------------------------------------------------

    async def _post_area(self, client: httpx.AsyncClient, body: dict[str, Any]) -> list[dict[str, Any]]:
        for attempt, delay in enumerate((*RETRY_DELAYS_S, None)):
            resp = await client.post(AREA_URL, json=body, timeout=90)
            if resp.status_code == 429 and delay is not None:
                log.info("[it] rate limited on %s, retry %d in %ss", body, attempt + 1, delay)
                await self.sleep(delay)
                continue
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success", True):
                raise RuntimeError(f"API returned success=false for {body}")
            return data.get("results") or []
        raise AssertionError("unreachable")

    async def fetch_api(self, client: httpx.AsyncClient) -> Dataset:
        resp = await client.get(REGIONS_URL, timeout=30)
        resp.raise_for_status()
        regions = [r["id"] for r in resp.json().get("results") or []]
        if not regions:
            raise RuntimeError("API returned no regions")
        results: list[dict[str, Any]] = []
        for i, region in enumerate(regions):
            if i:
                await self.sleep(REQUEST_PAUSE_S)
            results.extend(await self._post_area(client, {"region": region}))
        stations = await asyncio.to_thread(parse_area_results, results)
        if not stations:
            raise RuntimeError("API returned no stations")
        log.info("[it] Osservaprezzi API: %d stations from %d regions", len(stations), len(regions))
        return Dataset(
            stations=stations,
            data_date=datetime.now(ROME).date(),
            fetched_at=datetime.now(UTC),
        )

    # -- fallback: open-data CSV files --------------------------------------------

    async def fetch_csv(self, client: httpx.AsyncClient) -> Dataset:
        base = os.environ.get("FUELPRICE_IT_CSV_BASE_URL", CSV_BASE_URL).rstrip("/")

        async def get(name: str) -> str:
            resp = await client.get(
                f"{base}/{name}", follow_redirects=True,
                timeout=httpx.Timeout(60, connect=15),  # fail fast where the host is blocked
            )
            resp.raise_for_status()
            return _decode(resp.content)

        stations_csv, prices_csv = await asyncio.gather(*(get(n) for n in CSV_FILES))
        # Parsing ~100k rows is CPU-bound: keep the event loop responsive.
        return await asyncio.to_thread(build_dataset, stations_csv, prices_csv)

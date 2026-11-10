"""Italy: open data from the Ministero delle Imprese e del Made in Italy (MIMIT).

https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti
"""

from __future__ import annotations

import asyncio


import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.italy.parser import build_dataset

BASE_URL = "https://www.mimit.gov.it/images/exportCSV"
STATIONS_URL = f"{BASE_URL}/anagrafica_impianti_attivi.csv"
PRICES_URL = f"{BASE_URL}/prezzo_alle_8.csv"


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

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        async def get(url: str) -> str:
            resp = await client.get(url, timeout=60, follow_redirects=True)
            resp.raise_for_status()
            return _decode(resp.content)

        stations_csv, prices_csv = await asyncio.gather(get(STATIONS_URL), get(PRICES_URL))
        # Parsing ~100k rows is CPU-bound: keep the event loop responsive.
        return await asyncio.to_thread(build_dataset, stations_csv, prices_csv)

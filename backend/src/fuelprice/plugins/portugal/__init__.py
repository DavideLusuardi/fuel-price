"""Portugal: "Preços dos Combustíveis Online" of the Directorate-General for Energy (DGEG).

Every station must report its prices. The public site's API (undocumented) searches
one fuel type at a time; one page of up to 10000 rows covers the whole country, so a
full fetch is one request per fuel type (about 10, under a second each). Every price
has its own update time. There is no self/attended distinction.

Reusing the data formally requires a data-sharing agreement with DGEG.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.portugal.parser import FUELS, build_dataset

SEARCH_URL = "https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PesquisarPostos"
PAGE_SIZE = 10000
MAX_PAGES = 10
MAX_CONCURRENCY = 3


async def search_fuel(client: httpx.AsyncClient, fuel_id: int) -> list[dict[str, Any]]:
    """All rows for one fuel type, following pages if the country ever outgrows one."""
    rows: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        resp = await client.get(SEARCH_URL, timeout=60, params={
            "idsTiposComb": fuel_id, "idMarca": "", "idTipoPosto": "", "idDistrito": "",
            "idsMunicipios": "", "qtdPorPagina": PAGE_SIZE, "pagina": page,
        })
        resp.raise_for_status()
        body = resp.json()
        if not body.get("status"):
            raise ValueError(f"DGEG error for fuel {fuel_id}: {body.get('mensagem')!r}")
        batch = body.get("resultado") or []
        rows.extend(batch)
        total = batch[0].get("Quantidade", 0) if batch else 0
        if not batch or len(batch) < PAGE_SIZE or len(rows) >= total:
            return rows
    raise ValueError(f"DGEG fuel {fuel_id}: more than {MAX_PAGES} pages")


class PortugalPlugin(CountryPlugin):
    code = "pt"
    name = "Portugal"
    currency = "EUR"
    center = (39.6, -8.0)
    zoom = 7
    has_service_modes = False
    # Discount stations (Intermarché, independents) sell 12-20% below their neighbours,
    # mostly 98 petrol and LPG: the default 12% margin hid about 25 real prices.
    outlier_low = 0.20

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        async def one(fuel_id: int) -> tuple[int, list[dict[str, Any]]]:
            async with sem:
                return fuel_id, await search_fuel(client, fuel_id)

        results = dict(await asyncio.gather(*(one(f) for f in FUELS)))
        return await asyncio.to_thread(build_dataset, results)

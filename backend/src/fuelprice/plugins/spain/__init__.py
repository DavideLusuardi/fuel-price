"""Spain: fuel price service of the Ministry for the Ecological Transition (MITECO).

Every station must report its prices. One request returns all stations (about 12 MB of
JSON, about 10 s), updated every half hour. There are no per-price timestamps or
self/attended distinction. The server sometimes drops connections, so a failed
download is retried once.

The server only accepts the TLS 1.2 cipher AES256-GCM-SHA384 (RSA key exchange, no
forward secrecy). Python's default context does not offer it, and the server resets
the handshake, so this plugin downloads with its own client that adds that cipher.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl

import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.spain.parser import build_dataset

DATA_URL = (
    "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"
)
ATTEMPTS = 2
RETRY_DELAY = 5.0
LEGACY_CIPHER = "AES256-GCM-SHA384"
log = logging.getLogger(__name__)


def tls_context() -> ssl.SSLContext:
    """Python's default context (certificate checks included) plus the cipher the server needs."""
    ctx = ssl.create_default_context()
    tls12 = [c["name"] for c in ctx.get_ciphers() if c["protocol"] != "TLSv1.3"]
    ctx.set_ciphers(":".join([*tls12, LEGACY_CIPHER]))
    return ctx


class SpainPlugin(CountryPlugin):
    code = "es"
    name = "España"
    currency = "EUR"
    center = (40.2, -3.7)
    zoom = 6
    has_service_modes = False
    # Discount chains (Ballenoil, Alcampo, bonÀrea, Plenergy...) sell 12-25% below
    # their neighbours: with the default 12% margin about 220 real prices were hidden.
    outlier_low = 0.25

    async def _download(self, client: httpx.AsyncClient) -> bytes:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                resp = await client.get(
                    DATA_URL, headers={"Accept": "application/json"}, timeout=180, follow_redirects=True
                )
                resp.raise_for_status()
                return resp.content
            except httpx.TransportError:
                if attempt == ATTEMPTS:
                    raise
                log.warning("[es] download failed (attempt %d), retrying", attempt, exc_info=True)
                await asyncio.sleep(RETRY_DELAY)
        raise AssertionError("unreachable")

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        # A client of its own, keeping the caller's headers (User-Agent), so the weaker
        # cipher is only offered to this server.
        async with httpx.AsyncClient(headers=client.headers, verify=tls_context()) as own:
            content = await self._download(own)
        # json.loads on bytes also accepts a UTF-8 byte-order mark.
        return await asyncio.to_thread(lambda: build_dataset(json.loads(content)))

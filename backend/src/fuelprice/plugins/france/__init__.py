"""France: "prix des carburants" open data of the Ministry of the Economy.

Every station must report its prices (arrêté of 12 December 2006). The instant feed
is one ZIP with one XML file, refreshed about every 10 minutes, with an exact update
time for every price. There is no self/attended distinction.
"""

from __future__ import annotations

import asyncio
import io
import zipfile

import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.france.parser import build_dataset

DATA_URL = "https://donnees.roulez-eco.fr/opendata/instantane"


def unpack(content: bytes) -> bytes:
    """The XML inside the ZIP (or the body itself if it is already XML)."""
    if not content.startswith(b"PK"):
        return content
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not names:
            raise ValueError("no XML file in the archive")
        return zf.read(names[0])


class FrancePlugin(CountryPlugin):
    code = "fr"
    name = "France"
    currency = "EUR"
    center = (46.6, 2.4)
    zoom = 6
    has_service_modes = False

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        resp = await client.get(DATA_URL, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        return await asyncio.to_thread(lambda: build_dataset(unpack(resp.content)))

"""Croatia: fuel price system of the Ministry of Economy (mzoe-gor.hr).

The official site loads one gzipped JSON document with all stations and prices.
There are no per-price timestamps or self/attended distinction.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

from fuelprice.core.models import Dataset
from fuelprice.core.plugin import CountryPlugin
from fuelprice.plugins.croatia.parser import build_dataset

DATA_URL = "https://webservis.mzoe-gor.hr/data.gz"
ZAGREB = ZoneInfo("Europe/Zagreb")


def _decode(content: bytes) -> dict:
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    return json.loads(content)


def _last_modified(header: str | None) -> date | None:
    if not header:
        return None
    try:
        return parsedate_to_datetime(header).astimezone(ZAGREB).date()
    except (TypeError, ValueError):
        return None


class CroatiaPlugin(CountryPlugin):
    code = "hr"
    name = "Hrvatska"
    currency = "EUR"
    center = (44.5, 16.4)
    zoom = 7
    has_service_modes = False

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        resp = await client.get(DATA_URL, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        data_date = _last_modified(resp.headers.get("Last-Modified"))

        def parse() -> Dataset:
            return build_dataset(_decode(resp.content), data_date)

        return await asyncio.to_thread(parse)

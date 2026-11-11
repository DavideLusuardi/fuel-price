"""Fetch every country plugin and write the static data files for the web app.

    fuelprice-build --out ../frontend/public/data --previous https://example.org/app/data

``--previous`` (a URL or a directory with the last published files) is used to
  * keep serving the last good data, marked stale, when a source is down, and
  * remember since when a price is unchanged, for sources without timestamps.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from fuelprice.core.models import Dataset, FuelCategory
from fuelprice.core.outliers import flag_outliers
from fuelprice.core.plugin import CountryPlugin
from fuelprice.core.registry import discover_plugins
from fuelprice.export import FORMAT_VERSION, decode_country, dumps, encode_country

log = logging.getLogger("fuelprice.build")
USER_AGENT = "fuelprice/0.1 (+fuel station price map)"

PriceKey = tuple[str, str, bool | None]


async def load_previous(previous: str | None, code: str, client: httpx.AsyncClient) -> Dataset | None:
    """Last published dataset of a country, or None if unavailable."""
    if not previous:
        return None
    try:
        if previous.startswith(("http://", "https://")):
            resp = await client.get(f"{previous.rstrip('/')}/{code}.json", timeout=60, follow_redirects=True)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            doc = resp.json()
        else:
            path = Path(previous) / f"{code}.json"
            if not path.exists():
                return None
            doc = json.loads(path.read_bytes())
        return decode_country(doc)
    except Exception:
        log.warning("[%s] previous data unusable, starting fresh", code, exc_info=True)
        return None


def apply_history(dataset: Dataset, previous: Dataset | None) -> None:
    """Fill ``seen_since`` for prices the source publishes without a timestamp."""
    seen: dict[PriceKey, tuple[float, datetime]] = {}
    if previous is not None:
        for s in previous.stations:
            for p in s.prices:
                seen[(s.id, p.product, p.self_service)] = (p.price, p.seen_since or previous.fetched_at)
    for s in dataset.stations:
        for p in s.prices:
            if p.updated_at is not None:
                continue
            prev = seen.get((s.id, p.product, p.self_service))
            unchanged = prev is not None and abs(prev[0] - p.price) < 1e-9
            p.seen_since = prev[1] if unchanged else dataset.fetched_at


def _country_meta(plugin: CountryPlugin) -> dict[str, Any]:
    max_age = plugin.max_price_age
    return {
        "code": plugin.code,
        "name": plugin.name,
        "currency": plugin.currency,
        "center": list(plugin.center),
        "zoom": plugin.zoom,
        "has_service_modes": plugin.has_service_modes,
        "max_price_age_days": max_age.total_seconds() / 86400 if max_age is not None else None,
    }


async def build_country(
    plugin: CountryPlugin, out_dir: Path, previous: str | None, client: httpx.AsyncClient
) -> dict[str, Any]:
    meta = _country_meta(plugin)
    prev = await load_previous(previous, plugin.code, client)
    stale, error = False, None
    try:
        dataset = await plugin.fetch(client)
        apply_history(dataset, prev)
        log.info("[%s] fetched %d stations", plugin.code, len(dataset.stations))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.exception("[%s] fetch failed", plugin.code)
        if prev is None:
            return {**meta, "file": None, "hash": None, "stale": True, "error": error,
                    "station_count": 0, "suspect_count": 0, "categories": [], "data_date": None, "fetched_at": None}
        dataset, stale = prev, True
        log.warning("[%s] republishing previous data from %s", plugin.code, prev.fetched_at)

    suspect = flag_outliers(dataset, plugin.max_price_age, plugin.outlier_low)
    total = sum(len(s.prices) for s in dataset.stations)
    log.info("[%s] %d of %d prices look wrong and are left out of the map", plugin.code, suspect, total)

    body = dumps(encode_country(dataset))
    file = f"{plugin.code}.json"
    (out_dir / file).write_bytes(body)
    present = {p.category for s in dataset.stations for p in s.prices}
    return {
        **meta,
        "file": file,
        "hash": hashlib.sha256(body).hexdigest()[:16],
        "bytes": len(body),
        "stale": stale,
        "error": error,
        "station_count": len(dataset.stations),
        "suspect_count": suspect,
        "categories": [c.value for c in FuelCategory if c in present],
        "data_date": dataset.data_date.isoformat() if dataset.data_date else None,
        "fetched_at": dataset.fetched_at.isoformat(),
    }


async def build(
    out_dir: Path,
    plugins: dict[str, CountryPlugin],
    previous: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": USER_AGENT})
    try:
        entries = await asyncio.gather(
            *(build_country(p, out_dir, previous, client) for p in plugins.values())
        )
    finally:
        if own_client:
            await client.aclose()
    meta = {
        "v": FORMAT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "countries": sorted(entries, key=lambda e: e["name"]),
    }
    # Written last, so a reader never sees a meta.json pointing at missing files.
    (out_dir / "meta.json").write_bytes(dumps(meta))
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path, help="output directory")
    parser.add_argument("--previous", help="URL or directory of the last published data")
    parser.add_argument("--only", help="comma-separated country codes (default: all plugins)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    plugins = discover_plugins()
    if args.only:
        wanted = {c.strip().lower() for c in args.only.split(",")}
        plugins = {k: v for k, v in plugins.items() if k in wanted}
    if not plugins:
        log.error("No country plugins selected")
        return 1
    meta = asyncio.run(build(args.out, plugins, args.previous))
    for c in meta["countries"]:
        state = "STALE" if c["stale"] else "ok"
        log.info("%s %-10s %6d stations  %s", c["code"], c["name"], c["station_count"], state)
    return 0 if any(c["file"] for c in meta["countries"]) else 1


if __name__ == "__main__":
    sys.exit(main())

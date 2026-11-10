import json
from datetime import timedelta

import respx

from fuelprice.build import apply_history, build
from fuelprice.core.models import Dataset, FuelCategory, Price, Station
from fuelprice.core.registry import discover_plugins
from fuelprice.export import decode_country, encode_country
from fuelprice.plugins.croatia import CroatiaPlugin
from fuelprice.plugins.italy import ItalyPlugin
from fuelprice.plugins.slovenia import SloveniaPlugin
from tests.fakes import NOW, FakePlugin, make_dataset


def _undated(price: float, fetched_at=NOW) -> Dataset:
    return Dataset(
        fetched_at=fetched_at,
        stations=[Station(id="s", name="S", lat=1, lon=1, prices=[
            Price(category=FuelCategory.DIESEL, product="Dizel", price=price),
        ])],
    )


def test_registry_discovers_all_countries():
    plugins = discover_plugins()
    assert isinstance(plugins["it"], ItalyPlugin)
    assert isinstance(plugins["si"], SloveniaPlugin)
    assert isinstance(plugins["hr"], CroatiaPlugin)


def test_encode_decode_round_trip():
    ds = make_dataset()
    ds.stations[0].prices[0].seen_since = NOW - timedelta(days=3)
    doc = encode_country(ds)
    assert len(doc["products"]) == 4  # Diesel, Ultra, Mega, Petrol stored once each
    assert decode_country(json.loads(json.dumps(doc))) == ds


async def test_build_writes_country_files_and_meta(tmp_path):
    meta = await build(tmp_path, {"zz": FakePlugin()})
    [entry] = meta["countries"]
    assert entry["code"] == "zz" and entry["file"] == "zz.json" and not entry["stale"]
    assert entry["station_count"] == 3
    assert entry["categories"] == ["petrol", "diesel", "premium_diesel"]
    assert entry["max_price_age_days"] == 7
    assert entry["has_service_modes"] is True
    assert len(entry["hash"]) == 16
    assert json.loads((tmp_path / "meta.json").read_text()) == meta
    assert decode_country(json.loads((tmp_path / "zz.json").read_text())) == make_dataset()


async def test_build_republishes_previous_data_when_source_fails(tmp_path):
    prev_dir, out = tmp_path / "prev", tmp_path / "out"
    await build(prev_dir, {"zz": FakePlugin()})
    meta = await build(out, {"zz": FakePlugin(fail=True)}, previous=str(prev_dir))
    [entry] = meta["countries"]
    assert entry["stale"] is True and "source down" in entry["error"]
    assert entry["station_count"] == 3
    assert (out / "zz.json").read_bytes() == (prev_dir / "zz.json").read_bytes()


async def test_build_without_any_data_lists_country_as_unavailable(tmp_path):
    meta = await build(tmp_path, {"zz": FakePlugin(fail=True)})
    [entry] = meta["countries"]
    assert entry["file"] is None and entry["stale"] is True
    assert not (tmp_path / "zz.json").exists()


def test_history_keeps_date_of_unchanged_price():
    earlier = NOW - timedelta(days=5)
    prev = _undated(1.848, fetched_at=NOW - timedelta(hours=2))
    prev.stations[0].prices[0].seen_since = earlier
    ds = _undated(1.848)
    apply_history(ds, prev)
    assert ds.stations[0].prices[0].seen_since == earlier


def test_history_resets_date_when_price_changes():
    prev = _undated(1.848, fetched_at=NOW - timedelta(days=1))
    prev.stations[0].prices[0].seen_since = NOW - timedelta(days=5)
    ds = _undated(1.799)
    apply_history(ds, prev)
    assert ds.stations[0].prices[0].seen_since == NOW


def test_history_first_run_and_dated_sources():
    ds = _undated(1.848)
    apply_history(ds, None)
    assert ds.stations[0].prices[0].seen_since == NOW
    dated = make_dataset()
    apply_history(dated, None)
    assert all(p.seen_since is None for s in dated.stations for p in s.prices)


@respx.mock
async def test_previous_data_from_url(tmp_path):
    prev = _undated(1.848, fetched_at=NOW - timedelta(hours=2))
    prev.stations[0].prices[0].seen_since = NOW - timedelta(days=4)
    respx.get("https://example.org/app/data/zz.json").respond(200, json=encode_country(prev))
    meta = await build(tmp_path, {"zz": FakePlugin(_undated(1.848))}, previous="https://example.org/app/data/")
    assert not meta["countries"][0]["stale"]
    ds = decode_country(json.loads((tmp_path / "zz.json").read_text()))
    assert ds.stations[0].prices[0].seen_since == NOW - timedelta(days=4)


@respx.mock
async def test_previous_url_missing_is_fine(tmp_path):
    respx.get("https://example.org/data/zz.json").respond(404)
    meta = await build(tmp_path, {"zz": FakePlugin()}, previous="https://example.org/data")
    assert meta["countries"][0]["file"] == "zz.json"


def test_main_cli(tmp_path, monkeypatch):
    from fuelprice import build as build_mod

    monkeypatch.setattr(build_mod, "discover_plugins", lambda: {"zz": FakePlugin(), "yy": FakePlugin()})
    assert build_mod.main(["--out", str(tmp_path), "--only", "zz"]) == 0
    assert [c["code"] for c in json.loads((tmp_path / "meta.json").read_text())["countries"]] == ["zz"]

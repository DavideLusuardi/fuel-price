from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fuelprice.core.models import FuelCategory
from fuelprice.plugins.italy.parser import build_dataset, parse_prices, parse_stations

FIX = Path(__file__).parent / "fixtures"
ROME = ZoneInfo("Europe/Rome")


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_stations_reads_date_and_valid_rows():
    data_date, stations = parse_stations(_read("anagrafica.csv"))
    assert data_date == date(2026, 11, 9)
    # 60502 (no coords) and 11111 (zero coords) are dropped
    assert set(stations) == {"59183", "63381", "40820", "59690"}


def test_parse_stations_cleans_fields():
    _, stations = parse_stations(_read("anagrafica.csv"))
    s = stations["63381"]
    assert s.name == "19834 MONTALLEGRO"  # tab replaced, whitespace collapsed
    assert s.address == "SS.115 KM.158+302 S.N."
    assert s.brand == "Agip Eni"
    assert s.operator == "ENIMOOV S.P.A."
    assert s.city == "AGRIGENTO" and s.province == "AG"
    assert (s.lat, s.lon) == (37.38895, 13.351206)


def test_parse_stations_handles_pipe_inside_name():
    _, stations = parse_stations(_read("anagrafica.csv"))
    s = stations["40820"]
    assert s.name == "STOIL SIMPLE | gestori.prezzibenzina.it"
    assert s.address == "STR. PROV.LE 82 SPINETTA SALE 15122"
    assert s.city == "ALESSANDRIA"
    assert s.lat == 44.91704718250436


def test_parse_stations_accepts_comma_decimal_coords():
    _, stations = parse_stations(_read("anagrafica.csv"))
    assert stations["59690"].lat == 37.35285


def test_parse_prices():
    data_date, rows = parse_prices(_read("prezzi.csv"))
    assert data_date == date(2026, 11, 9)
    rows = list(rows)
    sid, p = rows[0]
    assert sid == "59183"
    assert p.product == "Benzina"
    assert p.category is FuelCategory.PETROL
    assert p.price == 2.349
    assert p.self_service is False
    assert p.updated_at == datetime(2026, 11, 4, 19, 30, 8, tzinfo=ROME)
    by_key = {(s, p.product): p for s, p in rows}
    assert by_key[("59690", "Gasolio")].price == 1.95  # comma decimal
    # sentinel/absurd prices are dropped
    assert ("40820", "Metano") not in by_key


def test_build_dataset_joins_and_skips_unknown_ids():
    ds = build_dataset(_read("anagrafica.csv"), _read("prezzi.csv"))
    assert ds.data_date == date(2026, 11, 9)
    by_id = {s.id: s for s in ds.stations}
    assert len(by_id["59183"].prices) == 4
    assert [p.product for p in by_id["63381"].prices] == ["Gasolio", "GPL"]
    assert "99999" not in by_id
    assert "60502" not in by_id

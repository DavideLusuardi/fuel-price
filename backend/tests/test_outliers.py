from datetime import timedelta

from fuelprice.core.models import Dataset, FuelCategory, Price, Station
from fuelprice.core.outliers import flag_outliers
from tests.fakes import NOW

DIESEL = FuelCategory.DIESEL


def _station(i: int, lat: float, lon: float, price: float, *, self_service=True, updated_at=NOW,
             category=DIESEL) -> Station:
    return Station(id=f"s{i}", name=f"S{i}", lat=lat, lon=lon, prices=[
        Price(category=category, product="Diesel", price=price, self_service=self_service, updated_at=updated_at),
    ])


def _cluster(lat: float, lon: float, prices: list[float], start: int = 0, **kw) -> list[Station]:
    """Stations spread over ~2 km around (lat, lon)."""
    return [_station(start + i, lat + (i % 5) * 0.004, lon + (i // 5) * 0.004, p, **kw)
            for i, p in enumerate(prices)]


def _suspects(ds: Dataset) -> set[str]:
    return {s.id for s in ds.stations for p in s.prices if p.suspect}


def _ds(stations: list[Station]) -> Dataset:
    return Dataset(fetched_at=NOW, stations=stations)


NORMAL = [1.80, 1.82, 1.79, 1.85, 1.81, 1.83, 1.78, 1.84, 1.80, 1.82]


def test_flags_price_far_below_neighbours():
    ds = _ds(_cluster(45.0, 11.0, [*NORMAL, 1.40]))
    assert flag_outliers(ds) == 1
    assert _suspects(ds) == {"s10"}


def test_keeps_cheap_but_plausible_price():
    ds = _ds(_cluster(45.0, 11.0, [*NORMAL, 1.65]))  # ~9% below the local median
    assert flag_outliers(ds) == 0


def test_flags_typo_far_above_neighbours_but_keeps_expensive_motorway_price():
    ds = _ds(_cluster(45.0, 11.0, [*NORMAL, 2.25, 18.1]))
    flag_outliers(ds)
    assert _suspects(ds) == {"s11"}


def test_compares_with_local_prices_not_country_average():
    # A cheap area 300 km away from an expensive one: neither is an outlier.
    cheap = _cluster(45.0, 11.0, [1.60, 1.62, 1.59, 1.61, 1.63, 1.60, 1.58, 1.62])
    pricey = _cluster(42.3, 11.0, [1.95, 1.97, 1.96, 1.98, 1.94, 1.95, 1.99, 1.96], start=100)
    ds = _ds(cheap + pricey)
    assert flag_outliers(ds) == 0


def test_groups_by_service_mode():
    # Self-service is normally cheaper than attended: compare like with like.
    self_ = _cluster(45.0, 11.0, NORMAL, self_service=True)
    attended = _cluster(45.0, 11.0, [p + 0.20 for p in NORMAL], start=100, self_service=False)
    lone_self = _station(200, 45.01, 11.01, 1.79, self_service=True)
    ds = _ds(self_ + attended + [lone_self])
    assert flag_outliers(ds) == 0


def test_groups_by_fuel_category():
    diesel = _cluster(45.0, 11.0, NORMAL)
    lpg = _cluster(45.0, 11.0, [0.75, 0.76, 0.74, 0.77, 0.75], start=100, category=FuelCategory.LPG)
    ds = _ds(diesel + lpg)
    assert flag_outliers(ds) == 0


def test_isolated_station_falls_back_to_country_median():
    near = _cluster(45.0, 11.0, NORMAL)
    far_ok = _station(100, 40.0, 16.0, 1.70)     # ~6% below the country median: kept
    far_bad = _station(101, 40.5, 16.5, 1.30)    # ~28% below: flagged
    ds = _ds([*near, far_ok, far_bad])
    flag_outliers(ds)
    assert _suspects(ds) == {"s101"}


def test_old_prices_are_not_used_as_reference():
    old = NOW - timedelta(days=60)
    # The neighbourhood's prices from two months ago were much lower than today's.
    stale = _cluster(45.0, 11.0, [1.50] * 15, start=100, updated_at=old)
    fresh = _cluster(45.0, 11.0, NORMAL)
    ds = _ds(stale + fresh)
    flag_outliers(ds, max_age=timedelta(days=7))
    assert _suspects(ds) == {s.id for s in stale}  # judged against today's prices


def test_non_positive_price_is_suspect():
    ds = _ds(_cluster(45.0, 11.0, [*NORMAL, 0.0]))
    flag_outliers(ds)
    assert _suspects(ds) == {"s10"}


def test_rerun_resets_previous_flags():
    ds = _ds(_cluster(45.0, 11.0, NORMAL))
    ds.stations[0].prices[0].suspect = True
    assert flag_outliers(ds) == 0
    assert _suspects(ds) == set()


def test_low_price_confirmed_by_a_neighbour_is_kept():
    # E.g. a duty-free zone: two stations agree on a price far below the area's.
    ds = _ds(_cluster(45.0, 11.0, [*NORMAL, 1.35, 1.36]))
    assert flag_outliers(ds) == 0


def test_high_price_is_flagged_even_when_confirmed():
    ds = _ds(_cluster(45.0, 11.0, [*NORMAL, 4.37, 4.49]))
    assert flag_outliers(ds) == 2


def test_isolated_low_price_confirmed_by_a_neighbour_is_kept():
    near = _cluster(45.0, 11.0, NORMAL)
    remote = [_station(100, 40.0, 16.0, 1.30), _station(101, 40.01, 16.01, 1.31)]
    ds = _ds([*near, *remote])
    assert flag_outliers(ds) == 0


def test_gas_fuels_get_a_wider_margin():
    cng = _cluster(45.0, 11.0, NORMAL, category=FuelCategory.CNG)
    cheap = _station(100, 45.002, 11.002, 1.50, category=FuelCategory.CNG)  # ~17% below: real cheap CNG
    wrong = _station(101, 45.006, 11.006, 1.00, category=FuelCategory.CNG)  # ~45% below
    ds = _ds([*cng, cheap, wrong])
    flag_outliers(ds)
    assert _suspects(ds) == {"s101"}

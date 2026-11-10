from datetime import UTC, date, datetime

import httpx

from fuelprice.core.models import Dataset, FuelCategory, Price, Station
from fuelprice.core.plugin import CountryPlugin

NOW = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)


def make_dataset() -> Dataset:
    def p(cat, product, price, self_service=None):
        return Price(category=cat, product=product, price=price, self_service=self_service, updated_at=NOW)

    return Dataset(
        data_date=date(2026, 11, 10),
        fetched_at=NOW,
        stations=[
            Station(id="a", name="A", brand="X", lat=1.0, lon=1.0, prices=[
                p(FuelCategory.DIESEL, "Diesel", 1.80, True),
                p(FuelCategory.DIESEL, "Diesel", 2.00, False),
                p(FuelCategory.PREMIUM_DIESEL, "Ultra", 1.95, True),
                p(FuelCategory.PREMIUM_DIESEL, "Mega", 1.90, True),
            ]),
            Station(id="b", name="B", brand="Y", lat=2.0, lon=2.0, prices=[
                p(FuelCategory.DIESEL, "Diesel", 1.70, True),
                p(FuelCategory.PETROL, "Petrol", 1.85, True),
            ]),
            Station(id="c", name="C", brand="Z", lat=3.0, lon=3.0, prices=[
                p(FuelCategory.DIESEL, "Diesel", 2.10, False),
            ]),
        ],
    )


class FakePlugin(CountryPlugin):
    code = "zz"
    name = "Fakeland"
    currency = "EUR"
    center = (2.0, 2.0)
    zoom = 7
    has_service_modes = True

    def __init__(self, dataset: Dataset | None = None, fail: bool = False):
        self.dataset = dataset or make_dataset()
        self.fail = fail
        self.calls = 0

    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        self.calls += 1
        if self.fail:
            raise RuntimeError("source down")
        return self.dataset.model_copy(deep=True)

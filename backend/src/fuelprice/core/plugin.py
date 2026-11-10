"""The contract every country plugin implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import ClassVar

import httpx

from fuelprice.core.models import Dataset


class CountryPlugin(ABC):
    """A data source for one country.

    Register an implementation under the ``fuelprice.countries`` entry-point group
    (see pyproject.toml) and the app picks it up automatically.
    """

    code: ClassVar[str]
    """ISO 3166-1 alpha-2 code, lower case (e.g. ``"it"``)."""
    name: ClassVar[str]
    currency: ClassVar[str] = "EUR"
    center: ClassVar[tuple[float, float]]
    """Initial map center as (lat, lon)."""
    zoom: ClassVar[int] = 6
    has_service_modes: ClassVar[bool] = False
    """True when the source distinguishes self-service and attended prices."""
    max_price_age: ClassVar[timedelta | None] = timedelta(days=7)
    """Prices not updated for longer than this are left out of the map (still shown in details)."""

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> Dataset:
        """Download and normalize the full station/price dataset."""

"""Country-independent data model shared by every plugin."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FuelCategory(StrEnum):
    """Normalized fuel categories. Plugins map their product names onto these."""

    PETROL = "petrol"
    DIESEL = "diesel"
    PREMIUM_PETROL = "premium_petrol"
    PREMIUM_DIESEL = "premium_diesel"
    LPG = "lpg"
    CNG = "cng"
    LNG = "lng"
    HVO = "hvo"
    OTHER = "other"


class Price(BaseModel):
    category: FuelCategory
    product: str = Field(description="Raw product name as published by the source")
    price: float
    self_service: bool | None = Field(
        default=None, description="True=self, False=attended, None=source has no such distinction"
    )
    updated_at: datetime | None = Field(default=None, description="When the source says the price was set")
    seen_since: datetime | None = Field(
        default=None,
        description="For sources without timestamps: first time the build saw this exact price",
    )
    suspect: bool = Field(
        default=False, description="Far off nearby prices, probably wrong; left out of the map (see core/outliers.py)"
    )


class Station(BaseModel):
    id: str
    name: str
    brand: str = ""
    operator: str = ""
    address: str = ""
    city: str = ""
    province: str = ""
    lat: float
    lon: float
    prices: list[Price] = Field(default_factory=list)


class Dataset(BaseModel):
    stations: list[Station]
    data_date: date | None = Field(default=None, description="Date the source refers to")
    fetched_at: datetime

import pytest

from fuelprice.core.models import FuelCategory as F
from fuelprice.plugins.italy.fuels import categorize

CASES = {
    "Benzina": F.PETROL,
    "Gasolio": F.DIESEL,
    "GPL": F.LPG,
    "Metano": F.CNG,
    "L-GNC": F.CNG,
    "GNL": F.LNG,
    "HVO": F.HVO,
    "HVOlution": F.HVO,
    "HVO100": F.HVO,
    "REHVO": F.HVO,
    "BCHVO": F.HVO,
    "Diesel HVO": F.HVO,
    "Gasolio Bio HVO": F.HVO,
    "GASOLIO HVO": F.HVO,
    "Blue Diesel": F.PREMIUM_DIESEL,
    "Supreme Diesel": F.PREMIUM_DIESEL,
    "Hi-Q Diesel": F.PREMIUM_DIESEL,
    "Gasolio speciale": F.PREMIUM_DIESEL,
    "Gasolio Premium": F.PREMIUM_DIESEL,
    "Diesel Shell V Power": F.PREMIUM_DIESEL,
    "V-Power Diesel": F.PREMIUM_DIESEL,
    "DieselMax": F.PREMIUM_DIESEL,
    "S-Diesel": F.PREMIUM_DIESEL,
    "E-DIESEL": F.PREMIUM_DIESEL,
    "Excellium Diesel": F.PREMIUM_DIESEL,
    "Blu Diesel Alpino": F.PREMIUM_DIESEL,
    "Gasolio artico": F.DIESEL,
    "Gasolio Alpino": F.DIESEL,
    "Gasolio Gelo": F.DIESEL,
    "Gasolio Artico Igloo": F.DIESEL,
    "Blue Super": F.PREMIUM_PETROL,
    "HiQ Perform+": F.PREMIUM_PETROL,
    "Benzina speciale": F.PREMIUM_PETROL,
    "Benzina WR 100": F.PREMIUM_PETROL,
    "Benzina Shell V Power": F.PREMIUM_PETROL,
    "V-Power": F.PREMIUM_PETROL,
    "F101": F.PREMIUM_PETROL,
    "F-101": F.PREMIUM_PETROL,
    "Benzina Plus 98": F.PREMIUM_PETROL,
    "Verde speciale": F.PREMIUM_PETROL,
    "Something odd": F.OTHER,
}


@pytest.mark.parametrize(("name", "expected"), CASES.items())
def test_categorize(name, expected):
    assert categorize(name) is expected

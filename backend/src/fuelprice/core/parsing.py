"""Small parsing helpers shared by country plugins."""

from __future__ import annotations

# Real pump prices in euro (per litre or kg) fall in this range. Sources use values
# such as 0.001 / 0.100 as placeholders and sometimes list bottled-gas prices.
# Plugins of countries with another currency pass their own range to valid_price.
PRICE_RANGE = (0.3, 4.5)


def clean(value: object) -> str:
    """Collapse whitespace (incl. tabs and non-breaking spaces); None becomes ''."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def number(value: object) -> float | None:
    """Parse a float accepting a comma decimal separator; None on failure."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def valid_price(value: object, price_range: tuple[float, float] = PRICE_RANGE) -> float | None:
    price = number(value)
    if price is None or not (price_range[0] <= price <= price_range[1]):
        return None
    return price

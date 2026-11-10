"""Small parsing helpers shared by country plugins."""

from __future__ import annotations

# Real pump prices (per litre or kg) fall in this range. Sources use values such
# as 0.001 / 0.100 as placeholders and sometimes list bottled-gas prices.
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


def valid_price(value: object) -> float | None:
    price = number(value)
    if price is None or not (PRICE_RANGE[0] <= price <= PRICE_RANGE[1]):
        return None
    return price

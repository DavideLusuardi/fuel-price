"""Maps Italian product names (MIMIT ``descCarburante``) to normalized categories.

Plain product names are matched exactly; everything else is a branded product
and goes through keyword rules. Unknown names fall back to ``OTHER`` and are
logged once so the rules can be extended.
"""

from __future__ import annotations

import logging
import re
from functools import cache

from fuelprice.core.models import FuelCategory as F

log = logging.getLogger(__name__)

EXACT: dict[str, F] = {
    "benzina": F.PETROL,
    "gasolio": F.DIESEL,
    "diesel": F.DIESEL,
    "gpl": F.LPG,
    "metano": F.CNG,
    "gnc": F.CNG,
    "l-gnc": F.CNG,
    "gnl": F.LNG,
}

# Winter diesel blends are priced like regular diesel.
_WINTER = re.compile(r"\b(artico|alpino|gelo|igloo)\b")
_PREMIUM_HINT = re.compile(r"\b(blue?|premium|speciale|plus|supreme|hi-?q|v-?power|excellium)\b")


def _rules(name: str) -> F | None:
    if "hvo" in name:
        return F.HVO
    if "gnl" in name or "lng" in name:
        return F.LNG
    if "metano" in name or "gnc" in name or "cng" in name:
        return F.CNG
    if "gpl" in name or "lpg" in name:
        return F.LPG
    if "diesel" in name or "gasolio" in name:
        if _WINTER.search(name) and not _PREMIUM_HINT.search(name):
            return F.DIESEL
        return F.PREMIUM_DIESEL
    if re.search(r"benzina|super|verde|ottani|v-?power|f-?101|perform", name):
        return F.PREMIUM_PETROL
    return None


@cache
def categorize(product: str) -> F:
    name = " ".join(product.lower().split())
    category = EXACT.get(name) or _rules(name)
    if category is None:
        log.warning("Unmapped Italian fuel product %r, using 'other'", product)
        return F.OTHER
    return category

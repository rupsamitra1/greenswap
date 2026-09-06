"""Transparent sticker, unit, and use-based price comparisons."""
from __future__ import annotations

import re


def infer_quantity(title: str) -> tuple[float | None, str | None]:
    text = title.lower().replace("fluid ounces", "fl oz").replace("ounces", "oz")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(fl\s*oz|oz|count|pack|ct)\b", text)
    if not match:
        return None, None
    quantity = float(match.group(1))
    unit = match.group(2).replace(" ", "")
    unit = "fl oz" if unit == "floz" else "item" if unit in {"count", "pack", "ct"} else unit
    return quantity, unit


def price_basis(product: dict) -> dict:
    price = product.get("price")
    quantity = product.get("unit_quantity")
    unit = product.get("unit_label")
    if not quantity:
        quantity, unit = infer_quantity(product.get("name") or product.get("title") or "")
    uses = product.get("estimated_uses")
    return {
        "sticker_price": price,
        "quantity": quantity,
        "unit": unit,
        "price_per_unit": round(price / quantity, 3) if price and quantity else None,
        "price_per_use": round(price / uses, 3) if price and uses else None,
        "estimated_uses": uses,
        "note": "Per-use values are demo estimates, not a guarantee" if uses else None,
    }

"""
King Soopers pricing — thin wrapper around instacart_pricing.py.

King Soopers is a Kroger-family banner that cannot be priced via the Kroger
REST API for Colorado locations (returns PRODUCT-4109-404). This module
provides the same public surface as before but delegates to the shared
Instacart session in instacart_pricing.py.
"""
from __future__ import annotations

from typing import Optional

from instacart_pricing import get_instacart_slug, price_all_instacart

KS_BANNERS: set[str] = {"king soopers", "king sooper", "kingsoopers", "city market"}


def is_king_soopers_store(store_name: str) -> bool:
    lower = store_name.lower()
    return any(b in lower for b in KS_BANNERS)


def price_all_ks(
    ingredients: dict,
    lat: float,
    lon: float,
    max_workers: int = 10,
) -> tuple[Optional[str], Optional[str], dict]:
    """
    Price all ingredients at the nearest King Soopers via Instacart.

    Returns (store_display_name, shop_id, prices).
    """
    return price_all_instacart(ingredients, lat, lon, "king-soopers", max_workers)

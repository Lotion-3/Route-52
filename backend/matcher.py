"""
Keyword matching between user grocery items and coupon/flyer entries.

Same strategy as the removed flipp_coupons.py: extract significant words
from both sides, require >=2 shared words for a match.
"""
import re
from typing import Optional

_STOP = frozenset({
    "the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "at",
    "with", "without", "fresh", "organic", "natural", "whole", "real",
    "all", "each", "every", "some", "any", "no", "not", "only", "just",
    "new", "old", "large", "small", "medium", "big", "little",
    "plus", "extra", "deluxe", "premium", "select", "choice", "value",
    "cut", "sliced", "diced", "minced", "grated", "shredded", "ground",
    "boneless", "skinless", "plain", "original", "traditional", "classic",
    "regular", "thin", "thick", "spicy", "mild", "hot", "sweet", "savory",
    "buy", "get", "free", "off", "save", "was", "now", "each", "lb", "oz",
})


def extract_keywords(text: str) -> set[str]:
    words = set()
    for part in re.split(r"[\s,;:/()\[\]\"'\-]+", text.lower().strip()):
        part = part.strip(".,!?$%#@*")
        if len(part) >= 3 and part not in _STOP and not part.isdigit():
            words.add(part)
    return words


def match_item_to_coupon(item_name: str, coupons: list[dict], min_shared: int = 2) -> Optional[dict]:
    item_keywords = extract_keywords(item_name)
    if not item_keywords:
        return None

    for c in coupons:
        coupon_keywords = set(c.get("keywords", []))
        if not coupon_keywords:
            coupon_keywords = extract_keywords(f"{c.get('brand', '')} {c.get('item_name', '')} {c.get('description', '')}")
        shared = len(item_keywords & coupon_keywords)
        if shared >= min_shared:
            return c
    return None

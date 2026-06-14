"""
Parse a Walmart cart text file (copy-pasted from the browser) into a clean
JSON price database with cart items and recommended items labeled separately.

Usage:
    python parse_walmart_cart.py testCache.txt
    python parse_walmart_cart.py testCache.txt --out walmart_prices.json
"""

import re
import json
import sys
from pathlib import Path

SKIP_LINES = {
    "best seller", "rollback", "flash deal", "reduced price", "clearance",
    "low stock", "only 1 left", "snap ebt eligible", "gift eligible",
    "gift eligible: original packaging",
    "100+ bought since yesterday", "in 200+ people's carts",
    "free 30-day returns", "free 90-day returns", "free 14-day returns",
    "free 365-day returns", "gifteligibleicon", "pro seller", "|",
    "view details", "(only one option can be selected at a time.)",
    "removesave for later", "max 1", "1", "", "add", "sponsored",
    "save with", "walmart plus", "options",
}

SECTION_MARKERS = {
    "add your essentials":    "essentials",
    "recommended with your order": "recommended",
}

def extract_price(line: str):
    m = re.match(r'Current price \$(\d+\.\d{2})', line, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.match(r'\$(\d+\.\d{2})', line)
    if m:
        return float(m.group(1))
    return None

def is_compact_duplicate(line: str) -> bool:
    # Compact prices have no decimal after first number: "$13125", "$27800$348.00"
    # Legitimate prices always have ".XX": "$131.25", "$238.00"
    m = re.match(r'^\$(\d+)(.*)', line)
    if not m:
        return False
    return not m.group(2).startswith('.')

def parse_cart(text: str) -> dict:
    lines = text.splitlines()

    sections = {"cart": {}, "essentials": {}, "recommended": {}}
    current_section = "cart"
    current_name = None

    for raw in lines:
        line = raw.strip()
        lower = line.lower()

        # Section detection
        if lower in SECTION_MARKERS:
            current_section = SECTION_MARKERS[lower]
            current_name = None
            continue

        # Skip junk
        if lower in SKIP_LINES:
            continue
        if is_compact_duplicate(line):
            continue
        if re.match(r'^(Sold and shipped by|Fulfilled by|Arrives|Order within|Shipping|Pickup|Delivery|See options)', line):
            current_name = None
            continue
        if re.match(r'^(In \d|In \d+K\+|[\d,K]+\+ (bought|people))', line, re.IGNORECASE):
            continue
        if re.match(r'^current price Now', line, re.IGNORECASE):
            continue
        if re.match(r'^\d+-Year Plan', line) or re.match(r'^[A-Z][a-z]+ TV (Wall Mount|Mounting)', line):
            continue
        if re.match(r'^(Remote |Tech Support|In-Home|Pro TV|Pro Furniture)', line):
            continue
        if re.match(r'^\d+ (items?|item)$', line):
            continue
        if line in ('Skip to Checkout Section', 'Skip to Total Summary',
                    'cart_gic_illustration', 'Pickup and delivery options',
                    'Reserve a time', 'Continue to checkout', 'Walmart',
                    'You save', 'Give feedback'):
            current_name = None
            continue
        if re.match(r'^(Size|Flavor|Actual Color|Count Per Pack|Multipack Quantity|Assembled Product Weight|Screen Size):', line):
            continue
        # Skip standalone savings/review lines
        if re.match(r'^You save$', line) or re.match(r'^\d+\.\d+ out of 5 Stars', line):
            continue
        if re.match(r'^\d+ reviews?$', line):
            continue

        price = extract_price(line)

        if price is not None:
            if current_name:
                bucket = sections[current_section]
                if current_name not in bucket:
                    bucket[current_name] = price
            current_name = None
        else:
            if len(line) > 10:
                current_name = line

    return sections


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python parse_walmart_cart.py <cart.txt> [--out output.json]")
        sys.exit(1)

    input_file = Path(args[0])
    output_file = Path(args[2]) if "--out" in args else input_file.with_suffix('.json')

    text = input_file.read_text(encoding='utf-8', errors='replace')
    sections = parse_cart(text)

    output_file.write_text(json.dumps(sections, indent=2), encoding='utf-8')

    for section, items in sections.items():
        print(f"{section}: {len(items)} items")
    print(f"-> {output_file}")


if __name__ == "__main__":
    main()

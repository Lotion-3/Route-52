"""
Seed stores into Supabase.

Usage:
    python -m backend.scripts.seed_stores
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config.env"))

from db import db

INDIANAPOLIS_STORES = [
    # ── Kroger ───────────────────────────────────────────────────────────
    {"chain": "Kroger", "name": "Kroger (Downtown)",      "lat": 39.7678, "lon": -86.1576, "address": "333 S Meridian St, Indianapolis, IN 46225"},
    {"chain": "Kroger", "name": "Kroger (Broad Ripple)",   "lat": 39.8710, "lon": -86.1426, "address": "2350 E 62nd St, Indianapolis, IN 46220"},
    {"chain": "Kroger", "name": "Kroger (Southside)",      "lat": 39.6800, "lon": -86.1500, "address": "701 US-31, Indianapolis, IN 46227"},
    {"chain": "Kroger", "name": "Kroger (Nora)",           "lat": 39.9080, "lon": -86.1000, "address": "1300 E 86th St, Indianapolis, IN 46240"},
    # ── Walmart ──────────────────────────────────────────────────────────
    {"chain": "Walmart", "name": "Walmart Supercenter (Castleton)",       "lat": 39.9080, "lon": -86.0700, "address": "5400 E 82nd St, Indianapolis, IN 46250"},
    {"chain": "Walmart", "name": "Walmart Supercenter (South)",           "lat": 39.7000, "lon": -86.1500, "address": "6940 US 31 S, Indianapolis, IN 46227"},
    {"chain": "Walmart", "name": "Walmart Neighborhood Market (Downtown)", "lat": 39.7700, "lon": -86.1600, "address": "1455 W 86th St, Indianapolis, IN 46260"},
    {"chain": "Walmart", "name": "Walmart Supercenter (West)",            "lat": 39.7800, "lon": -86.2800, "address": "10615 E Washington St, Indianapolis, IN 46229"},
    # ── ALDI ─────────────────────────────────────────────────────────────
    {"chain": "ALDI", "name": "ALDI (Downtown)",  "lat": 39.7650, "lon": -86.1550, "address": "1011 N Shadeland Ave, Indianapolis, IN 46219"},
    {"chain": "ALDI", "name": "ALDI (West)",      "lat": 39.7700, "lon": -86.2800, "address": "5151 W 38th St, Indianapolis, IN 46254"},
    {"chain": "ALDI", "name": "ALDI (South)",     "lat": 39.6900, "lon": -86.1500, "address": "7310 US 31 S, Indianapolis, IN 46227"},
    {"chain": "ALDI", "name": "ALDI (North)",     "lat": 39.8800, "lon": -86.1200, "address": "5430 E 82nd St, Indianapolis, IN 46250"},
    # ── Costco ───────────────────────────────────────────────────────────
    {"chain": "Costco", "name": "Costco (Merchant's Pointe)", "lat": 39.9220, "lon": -86.0640, "address": "3500 E 96th St, Indianapolis, IN 46240"},
    {"chain": "Costco", "name": "Costco (South)",             "lat": 39.6800, "lon": -86.1300, "address": "4250 Southport Crossing Dr, Indianapolis, IN 46237"},
    # ── Meijer ───────────────────────────────────────────────────────────
    {"chain": "Meijer", "name": "Meijer (Castleton)", "lat": 39.9100, "lon": -86.0900, "address": "5980 E 86th St, Indianapolis, IN 46250"},
    {"chain": "Meijer", "name": "Meijer (Greenwood)", "lat": 39.6200, "lon": -86.1190, "address": "850 US 31 N, Greenwood, IN 46142"},
    {"chain": "Meijer", "name": "Meijer (Avon)",      "lat": 39.7600, "lon": -86.3700, "address": "10790 E US Hwy 36, Avon, IN 46123"},
]


def seed():
    existing = {s["chain"] for s in db.get_all_stores()}
    new = [s for s in INDIANAPOLIS_STORES if s["chain"] not in existing]

    if not new:
        print("Stores already seeded — nothing to do.")
        return

    count = db.bulk_create_stores(new)
    print(f"Inserted {count} store(s):")
    for s in new:
        print(f"  {s['chain']:8s} → {s['name']}")


if __name__ == "__main__":
    seed()

"""
One-time (or occasionally re-run) offline build: turn Target's public store
sitemap into a local {store_id -> lat/lon} directory, so target_pricing.py
can resolve "nearest store" WITHOUT ever calling RedSky's nearby_stores_v1 --
confirmed dead (403/captcha via curl_cffi for ANY cookie, including zero
cookies, for ANY postal code, including the cookie's own home location).

Store pages themselves are client-side rendered (no lat/lon in the raw
HTML), so this geocodes each store's sitemap SLUG instead (e.g.
"los-angeles-eagle-rock" -> "los angeles eagle rock, USA") via Nominatim.
This is a heuristic, not the store's exact street address, but it's a large
accuracy improvement over the status quo (every user gets a hardcoded
Indianapolis store regardless of location) and has zero WAF exposure --
sitemaps and Nominatim are both unauthenticated, un-WAF'd surfaces.

Runtime: ~1 req/sec (Nominatim's usage policy) x ~2000 stores =~ 30-35 min.
Re-run only if Target's store footprint changes meaningfully -- store
locations don't change often, so this isn't on any schedule.

Usage:
    python build_target_store_directory.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from curl_cffi import requests as ccffi
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

_SITEMAP_INDEX = "https://www.target.com/sitemap_stores-index.xml.gz"
_OUTPUT = Path(__file__).parent / "target_store_directory.json"
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_STORE_URL_RE = re.compile(r"/sl/([^/]+)/(\d+)\s*$")

# Sanity bounds for continental US + AK/HI/PR -- reject anything a bad
# geocode match places outside real Target territory.
_LAT_RANGE = (17.0, 72.0)
_LON_RANGE = (-180.0, -65.0)


def _fetch(url: str) -> str:
    resp = ccffi.get(url, impersonate="chrome", timeout=30)
    resp.raise_for_status()
    return resp.text


def _sitemap_shard_urls() -> list[str]:
    index_text = _fetch(_SITEMAP_INDEX)
    shards = _LOC_RE.findall(index_text)
    if not shards:
        raise RuntimeError("Sitemap index had no <loc> entries -- format may have changed.")
    return shards


def _store_entries() -> list[tuple[str, str]]:
    """Returns [(slug, store_id), ...] across every sitemap shard."""
    entries: list[tuple[str, str]] = []
    for shard_url in _sitemap_shard_urls():
        text = _fetch(shard_url)
        for loc in _LOC_RE.findall(text):
            m = _STORE_URL_RE.search(loc)
            if m:
                entries.append((m.group(1), m.group(2)))
    return entries


def _in_bounds(lat: float, lon: float) -> bool:
    return _LAT_RANGE[0] <= lat <= _LAT_RANGE[1] and _LON_RANGE[0] <= lon <= _LON_RANGE[1]


def main() -> int:
    print("Fetching store sitemap...", flush=True)
    entries = _store_entries()
    print(f"Found {len(entries)} stores. Geocoding (~1/sec, ~{len(entries) / 60:.0f} min)...\n", flush=True)

    geolocator = Nominatim(user_agent="basketbuddy_target_store_directory")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.05)

    directory: list[dict] = []
    skipped = 0
    for i, (slug, store_id) in enumerate(entries):
        query = slug.replace("-", " ") + ", USA"
        try:
            loc = geocode(query, timeout=10)
        except Exception as e:
            loc = None
            print(f"  [{i + 1}/{len(entries)}] {store_id:6s} {slug:40s} ERROR {repr(e)[:60]}", flush=True)

        if loc and _in_bounds(loc.latitude, loc.longitude):
            directory.append({
                "store_id": store_id,
                "slug": slug,
                "lat": round(loc.latitude, 5),
                "lon": round(loc.longitude, 5),
            })
        else:
            skipped += 1
            if (i + 1) % 50 == 0 or loc is None:
                reason = "no match" if not loc else "out of bounds"
                print(f"  [{i + 1}/{len(entries)}] {store_id:6s} {slug:40s} SKIP ({reason})", flush=True)

        if (i + 1) % 100 == 0:
            print(f"  ...{i + 1}/{len(entries)} processed, {len(directory)} resolved, "
                  f"{skipped} skipped so far", flush=True)

    _OUTPUT.write_text(json.dumps(directory, indent=2))
    print(f"\nWrote {len(directory)} stores to {_OUTPUT} ({skipped} skipped/unresolved).", flush=True)
    return 0 if directory else 1


if __name__ == "__main__":
    sys.exit(main())

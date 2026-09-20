"""
Probe: which Kroger-family regional banners does Google Places actually
surface via places_nearby(keyword=...)?

kroger_async.py already knows how to route 20 Kroger-family banners (see
KROGER_BANNERS / BANNER_TO_CHAIN) to the right Kroger API `chain` code, and
kingsoopers_pricing.py has an Instacart fallback for King Soopers specifically
(the Kroger API is known to return empty for CO King Soopers). But
config.STORE_KEYWORDS only contains the literal string "Kroger", and
geo_utils.find_eligible_stores_google() does exactly one
places_nearby(keyword=...) call per STORE_KEYWORDS entry — so King Soopers,
Ralphs, Fred Meyer, etc. are never found as candidate stores today, no matter
how much pricing code already exists for them.

This empirically checks, per banner, whether a places_nearby search for that
banner's name actually returns a real grocery store near a city where the
banner is known to operate — i.e. whether adding it to STORE_KEYWORDS would
surface anything at all, before touching any pricing code.

Costs a small amount of real Google Places API quota (one places_nearby call
per banner, ~20 calls total).

Usage:
    python probe_kroger_banners.py
"""
from __future__ import annotations

import re
import time

import config
import googlemaps

gmaps = googlemaps.Client(key=config.GOOGLE_MAPS_API_KEY)

# banner -> a real city near where that banner actually operates. Kroger's
# banners are strictly regional — testing "King Soopers" near NYC would
# always return nothing even though the banner is real and priceable.
_TEST_MARKETS: dict[str, tuple[float, float]] = {
    "Kroger":        (39.1031, -84.5120),   # Cincinnati, OH -- control/baseline
    "King Soopers":  (39.7392, -104.9903),  # Denver, CO
    "City Market":   (39.0639, -108.5506),  # Grand Junction, CO (also UT/NM/WY)
    "Dillons":       (37.6872, -97.3301),   # Wichita, KS
    "Food 4 Less":   (34.0522, -118.2437),  # Los Angeles, CA
    "Foods Co":      (36.7378, -119.7871),  # Fresno, CA -- confirmed via foodsco.net store list
    "Fred Meyer":    (45.5152, -122.6784),  # Portland, OR
    "Fry's":         (33.4484, -112.0740),  # Phoenix, AZ
    "Gerbes":        (38.9517, -92.3341),   # Columbia, MO -- confirmed (2900 Paris Rd store)
    "Harris Teeter": (35.2271, -80.8431),   # Charlotte, NC
    "Jay C":         (38.9598, -85.8905),   # Seymour, IN -- JayC's HQ city (was wrongly Columbus, IN)
    "Mariano's":     (41.8781, -87.6298),   # Chicago, IL
    "Pay-Less":      (40.1934, -85.3863),   # Muncie, IN -- Pay Less is central-IN only (Anderson/Lafayette/
                                             # Muncie/West Lafayette), NOT Missouri as originally guessed
    "Pick 'n Save":  (43.0389, -87.9065),   # Milwaukee, WI
    "Metro Market":  (43.0731, -89.4012),   # Madison, WI -- confirmed still open (Cottage Grove Rd)
    "QFC":           (47.6062, -122.3321),  # Seattle, WA
    "Ralphs":        (34.0522, -118.2437),  # Los Angeles, CA
    "Ruler Foods":   (38.2527, -85.7585),   # Louisville, KY -- IN has more locations (15) but this
                                             # borders the IN/KY/OH cluster where most of the 46 stores sit
    "Smith's":       (40.7608, -111.8910),  # Salt Lake City, UT
    "Baker's":       (41.2565, -95.9345),   # Omaha, NE
    # "Owen's" deliberately omitted: confirmed retired in Aug 2020 -- all 3
    # ex-Owen's stores (Huntington/Ligonier/Warsaw, IN) rebranded to plain
    # "Kroger" that same week. Still sits in kroger_async.KROGER_BANNERS as
    # harmless dead weight, but there is nothing left to search for it here.
    "Copps":         (44.5133, -88.0133),   # Green Bay, WI -- LOW CONFIDENCE: most sources say Copps was
                                             # fully rebranded to Pick 'n Save in 2017, but a couple of
                                             # 2026-dated Yelp listings still use the name. Worth one test
                                             # call to settle it either way.
}


# Mirrors geo_utils.find_eligible_stores_google()'s _is_valid_grocery() exactly
# (those sets are local to that function, not importable, so duplicated here --
# keep in sync with geo_utils.py if that filter ever changes). Without this,
# the FIRST result for a lot of these keywords is a same-name pharmacy/fuel-
# center/money-services kiosk, not the actual grocery store -- production
# would correctly skip those and keep walking; a naive "first substring match"
# probe would not, and would wrongly call the banner a hit off a pharmacy.
_GROCERY_TYPES = {'grocery_or_supermarket', 'supermarket', 'store',
                  'department_store', 'shopping_mall', 'food'}
_SUPERMARKET_TYPES = {'supermarket', 'grocery_or_supermarket',
                      'department_store', 'shopping_mall'}


def _norm(s: str) -> str:
    """Lowercase, punctuation -> space (not deleted -- "Pay-Less" must still
    match "Pay Less"), collapse whitespace. Lenient matching for this probe
    only; still worth a manual look at the raw name printed below before
    picking the exact string to add to STORE_KEYWORDS."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]", " ", s.lower())).strip()


def _is_valid_grocery(place: dict) -> bool:
    name = place.get("name", "")
    if any(term in name.lower() for term in config.EXCLUDED_STORE_TERMS):
        return False
    types = set(place.get("types", []))
    if not (types & _GROCERY_TYPES):
        return False
    if ({"gas_station", "car_repair"} & types) and not (types & _SUPERMARKET_TYPES):
        return False
    return True


def probe(keyword: str, location: tuple[float, float]) -> tuple[dict | None, list[dict]]:
    """Walk results nearest-first (same order production consumes them) and
    return the first one that would actually survive _is_valid_grocery, plus
    everything that got skipped along the way (for the MISS explanation)."""
    resp = gmaps.places_nearby(location=location, keyword=keyword, rank_by="distance")
    results = resp.get("results", [])
    skipped = []
    for place in results:
        if _norm(keyword) not in _norm(place.get("name", "")):
            continue  # not actually this banner -- Places' keyword match can be loose
        if _is_valid_grocery(place):
            return place, skipped
        skipped.append(place)
    return None, skipped


def main() -> None:
    print(f"Probing {len(_TEST_MARKETS)} Kroger-family banners against Google Places...\n", flush=True)
    working, dead = [], []
    for keyword, loc in _TEST_MARKETS.items():
        try:
            winner, skipped = probe(keyword, loc)
        except Exception as e:
            print(f"  {keyword:15s}  ERROR: {repr(e)[:150]}", flush=True)
            dead.append(keyword)
            continue
        if winner:
            print(f"  {keyword:15s}  OK   -> {winner['name']!r}  ({winner.get('vicinity', '')})  "
                  f"types={winner.get('types', [])[:3]}", flush=True)
            working.append(keyword)
        else:
            if skipped:
                reasons = ", ".join(f"{s['name']!r} ({s.get('types', [])[:2]})" for s in skipped[:3])
                print(f"  {keyword:15s}  MISS -> only non-grocery matches nearby: {reasons}", flush=True)
            else:
                print(f"  {keyword:15s}  MISS -> no matching results at all near this location", flush=True)
            dead.append(keyword)
        time.sleep(0.2)  # no need to hammer the API

    print(f"\n{'=' * 70}")
    print(f"WORKING ({len(working)}): {working}")
    print(f"NOT FOUND ({len(dead)}): {dead}")


if __name__ == "__main__":
    main()

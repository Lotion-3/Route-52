"""
Probe 11 — DECISIVE Costco grocery-priceability test (fresh cloakbrowser).

Settles the one open question from probe9 (which got Akamai-blocked mid-run):
  For each basket term — fresh (milk/eggs) AND non-perishable (rice/oil/coffee/
  canned tuna/peanut butter) — does the gdx-api search->summary pipeline return
  a REAL onlinePrice, and via which delivery channel?

Method (mirrors the working bits of probe5/6/9):
  1. Launch cloakbrowser, warm www.costco.com (Akamai + gdx cookies).
  2. Trigger ONE real in-page search so we capture a *fresh* client-identifier
     header + visitorId straight from the browser's own XHR (stale IDs 401).
  3. For each term: POST the gdx search API -> result IDs; GET the summary API
     -> read childCatalogData[].displayPrice.onlinePrice. Record dispPrice flag,
     warehouseNumber, and whether the item looks like real grocery.
  4. Print a verdict table + save .cache/costco_probe11.json.

If www.costco.com returns Akamai "Access Denied" from this IP, that is itself
the finding (datacenter IP blocked -> same failure mode a Render deploy hits).

Run:  python probe_costco11.py
"""
import json, time, os
from urllib.parse import quote

SEARCH_API  = "https://gdx-api.costco.com/catalog/search/api/v1/search"
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
CLIENT_ID   = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"

TERMS = [
    ("milk",          "fresh"),
    ("eggs",          "fresh"),
    ("chicken breast","fresh"),
    ("bananas",       "fresh"),
    ("white rice",    "dry"),
    ("olive oil",     "dry"),
    ("coffee",        "dry"),
    ("canned tuna",   "dry"),
    ("peanut butter", "dry"),
    ("paper towels",  "household"),
]

GROCERY_WORDS = ("milk","egg","rice","oil","coffee","tuna","peanut","butter",
                 "banana","chicken","organic","kirkland","cereal","water","towel",
                 "snack","sauce","bean","flour","sugar","nut","juice")

os.makedirs(".cache", exist_ok=True)

captured = {"client_identifier": None, "visitor_id": None, "search_headers": {}}


def main():
    from cloakbrowser import launch
    print("[probe11] Launching cloakbrowser (headless, no proxy) ...")
    browser = launch(headless=True)
    ctx = browser.new_context()

    def on_request(req):
        if "catalog/search/api" in req.url and not captured["client_identifier"]:
            try:
                h = dict(req.all_headers())
            except Exception:
                h = dict(req.headers)
            captured["search_headers"] = {k: v for k, v in h.items() if not k.startswith(":")}
            captured["client_identifier"] = h.get("client-identifier")
            try:
                body = json.loads(req.post_data or "{}")
                captured["visitor_id"] = body.get("visitorId")
            except Exception:
                pass
            print(f"[probe11] Captured fresh client-identifier="
                  f"{captured['client_identifier']} visitorId={captured['visitor_id']}")

    page = ctx.new_page()
    page.on("request", on_request)

    print("[probe11] Warming homepage ...")
    try:
        page.goto("https://www.costco.com/", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"[probe11] homepage goto: {e!r}")
    time.sleep(3)

    # Check for Akamai block right away
    try:
        title = page.title()
    except Exception:
        title = "(lost)"
    print(f"[probe11] Homepage title: {title!r}  url={page.url}")
    if "Access Denied" in title:
        print("[probe11] *** AKAMAI BLOCK on homepage — datacenter IP flagged. "
              "Direct path not viable from this IP. ***")

    # Trigger a real search to harvest a fresh client-identifier
    print("[probe11] Triggering a real in-page search for 'milk' ...")
    try:
        page.goto("https://www.costco.com/CatalogSearch?keyword=milk&pageSize=24",
                  wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"[probe11] search goto: {e!r}")
    time.sleep(5)
    try:
        stitle = page.title()
    except Exception:
        stitle = "(lost)"
    print(f"[probe11] Search page title: {stitle!r}")

    cid = captured["client_identifier"]
    if not cid:
        # Fall back to the last-known captured id (may 401)
        cid = "168287ea-1201-45f6-9b45-5bbea49f8ee7"
        print(f"[probe11] No fresh id captured — falling back to known id {cid}")

    headers = {
        "client-identifier": cid,
        "client_id": "USBC",
        "locale": "en-US",
        "searchresultprovider": "GRS",
        "content-type": "application/json",
        "accept": "*/*",
        "origin": "https://www.costco.com",
        "referer": "https://www.costco.com/",
    }
    vid = captured["visitor_id"] or "83099816520155961790818054284274511765"

    results = {}
    for term, cat in TERMS:
        body = {
            "visitorId": vid, "query": term, "pageSize": 24, "offset": 0,
            "searchMode": "page", "personalizationEnabled": False,
            "warehouseId": "347-wh", "shipToPostal": "46032", "shipToState": "IN",
            "deliveryLocations": ["347-wh"],
        }
        try:
            sr = ctx.request.fetch(SEARCH_API, method="POST", headers=headers,
                                   data=json.dumps(body), timeout=30000)
        except Exception as e:
            print(f"  {term:14s}: search EXC {e}")
            results[term] = {"category": cat, "error": str(e)[:80]}
            continue
        if sr.status != 200:
            print(f"  {term:14s}: search HTTP {sr.status}  {sr.text()[:120]}")
            results[term] = {"category": cat, "search_status": sr.status}
            continue
        ids = [r["id"] for r in json.loads(sr.text()).get("searchResult", {}).get("results", [])]

        priced = []
        if ids:
            sum_url = (f"{SUMMARY_API}?clientId={CLIENT_ID}"
                       f"&items={','.join(ids[:20])}&whsNumber=347&locales=en-us")
            sresp = ctx.request.get(sum_url, headers={k: v for k, v in headers.items()
                                                      if k != "content-type"}, timeout=30000)
            if sresp.status == 200:
                for p in json.loads(sresp.text()).get("productData", []):
                    name = ""
                    for d in (p.get("descriptions") or []):
                        if d.get("languageKey") == "en-US":
                            name = d.get("object", {}).get("shortDescription", "")
                            break
                    best = None; whs = None
                    for c in (p.get("childCatalogData") or []):
                        dp = c.get("displayPrice")
                        if dp and dp.get("onlinePrice"):
                            op = dp["onlinePrice"]
                            if best is None or op < best:
                                best, whs = op, dp.get("warehouseNumber")
                    looks_grocery = any(w in name.lower() for w in GROCERY_WORDS)
                    if best:
                        priced.append({"id": p["id"], "name": name[:55], "price": best,
                                       "whs": whs, "cartOnly": p.get("dispPriceInCartOnly"),
                                       "grocery": looks_grocery})
            else:
                results[term] = {"category": cat, "search_ids": len(ids),
                                 "summary_status": sresp.status}
                print(f"  {term:14s}: {len(ids):2d} ids, summary HTTP {sresp.status}")
                continue

        groc = [x for x in priced if x["grocery"]]
        results[term] = {"category": cat, "search_ids": len(ids),
                         "priced": len(priced), "grocery_priced": len(groc),
                         "samples": groc[:4] or priced[:2]}
        tag = f"{len(groc)} grocery-priced" if groc else (f"{len(priced)} priced (non-grocery)" if priced else "0 priced")
        print(f"  {term:14s}[{cat:9s}]: {len(ids):2d} ids -> {tag}")
        for s in (groc[:3] or priced[:1]):
            print(f"        ${s['price']:8.2f} whs={s['whs']} cartOnly={s['cartOnly']} "
                  f"groc={s['grocery']}  {s['name']}")
        time.sleep(1.0)

    with open(".cache/costco_probe11.json", "w") as f:
        json.dump({"captured": captured, "results": results}, f, indent=2)

    print("\n=== VERDICT ===")
    any_grocery = any(v.get("grocery_priced", 0) > 0 for v in results.values())
    if any_grocery:
        print("  Some grocery items ARE directly priceable via gdx-api:")
        for t, v in results.items():
            if v.get("grocery_priced", 0) > 0:
                print(f"    {t}: {v['grocery_priced']} priced grocery items")
    else:
        print("  NO grocery items priceable directly. costco.com search surfaces "
              "ship-to-home merchandise only; fresh/warehouse grocery is not in the\n"
              "  public catalog. Instacart same-day remains the only grocery source.")
    print("\nSaved .cache/costco_probe11.json")

    page.close(); ctx.close(); browser.close()
    print("[probe11] Done.")


if __name__ == "__main__":
    main()

"""
Probe 14 — capture the REAL search XHR template + confirm dry-goods grocery
pricing. This is the make-or-break test for gdx-api grocery pricing.

Strategy: the search RESULTS PAGE, when it renders, fires the SPA's own
authenticated search + products/summary XHRs. Akamai blocks that page
intermittently from this datacenter IP, so we RETRY the page load until one
succeeds, then intercept:
  * the real search request  -> exact method/url/headers/body template
  * the products/summary responses (route) -> real product names + prices

Terms are DRY GOODS (what costco.com 2-day actually sells), not fresh.

Run:  python probe_costco14.py
"""
import json, time, os
from urllib.parse import quote
os.makedirs(".cache", exist_ok=True)

TERMS = ["olive oil", "coffee", "rice", "canned tuna"]
MAX_TRIES = 6

real_search = {}          # captured real search request template
summary_products = {}     # id -> product (from route interception)


def main():
    from cloakbrowser import launch
    print("[probe14] Launching cloakbrowser ...")
    browser = launch(headless=True)
    ctx = browser.new_context()

    def on_request(req):
        if "catalog/search/api" in req.url and req.method == "POST" and "template" not in real_search:
            try:
                h = dict(req.all_headers())
            except Exception:
                h = dict(req.headers)
            real_search["template"] = {
                "url": req.url,
                "headers": {k: v for k, v in h.items() if not k.startswith(":")},
                "body": req.post_data or "",
            }
            print(f"[probe14] *** Captured REAL search XHR ({len(h)} headers) ***")

    def handle_summary_route(route):
        try:
            resp = route.fetch()
            if resp.status == 200:
                try:
                    for p in json.loads(resp.body()).get("productData", []):
                        summary_products[p["id"]] = p
                except Exception:
                    pass
            route.fulfill(response=resp)
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    ctx.route("**/catalog/product/product-api/v1/products/summary**", handle_summary_route)

    page = ctx.new_page()
    page.on("request", on_request)
    print("[probe14] Warming homepage ...")
    try:
        page.goto("https://www.costco.com/", wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(3)

    for term in TERMS:
        url = f"https://www.costco.com/CatalogSearch?keyword={quote(term)}&pageSize=24"
        rendered = False
        for attempt in range(1, MAX_TRIES + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"  [{term}] try {attempt}: goto err {e!r}")
                time.sleep(2 + attempt)
                continue
            time.sleep(4)
            try:
                title = page.title()
            except Exception:
                title = "(lost)"
            if "Access Denied" in title:
                print(f"  [{term}] try {attempt}: Akamai Access Denied, retrying ...")
                time.sleep(2 + attempt * 1.5)
                continue
            rendered = True
            print(f"  [{term}] try {attempt}: RENDERED — title={title!r}")
            break
        if not rendered:
            print(f"  [{term}] never rendered after {MAX_TRIES} tries (Akamai). "
                  f"Need residential proxy.")
            continue
        time.sleep(4)  # let summary XHRs fire

    # Report captured real search template
    print("\n=== REAL SEARCH XHR TEMPLATE ===")
    if real_search.get("template"):
        t = real_search["template"]
        print(f"URL: {t['url']}")
        print(f"Body: {t['body'][:400]}")
        print("Headers:")
        for k, v in sorted(t["headers"].items()):
            vv = (v[:70] + "…") if k.lower() == "cookie" else v
            print(f"  {k}: {vv}")
        with open(".cache/costco_search_template.json", "w") as f:
            json.dump(t, f, indent=2)
        print("Saved .cache/costco_search_template.json")
    else:
        print("  (never captured — search page never rendered)")

    # Report priced grocery products from summary interception
    print(f"\n=== INTERCEPTED PRODUCTS ({len(summary_products)}) ===")
    grocery_hits = []
    for pid, p in summary_products.items():
        name = ""
        for d in (p.get("descriptions") or []):
            if d.get("languageKey") == "en-US":
                name = d.get("object", {}).get("shortDescription", ""); break
        best, whs = None, None
        for c in (p.get("childCatalogData") or []):
            dp = c.get("displayPrice")
            if dp and dp.get("onlinePrice"):
                op = dp["onlinePrice"]
                if best is None or op < best: best, whs = op, dp.get("warehouseNumber")
        low = name.lower()
        is_groc = any(w in low for w in ("oil","coffee","rice","tuna","kirkland","organic",
                                          "snack","sauce","bean","cereal","nut","water","can "))
        if best and is_groc:
            grocery_hits.append((best, name[:60], whs, p.get("dispPriceInCartOnly")))
    for price, name, whs, cart in sorted(grocery_hits)[:25]:
        print(f"  ${price:8.2f} whs={whs} cart={cart}  {name}")
    print(f"\n  -> {len(grocery_hits)} priced grocery-ish products intercepted")

    with open(".cache/costco_probe14_products.json", "w") as f:
        json.dump(list(summary_products.values()), f, indent=2)

    page.close(); ctx.close(); browser.close()
    print("[probe14] Done.")


if __name__ == "__main__":
    main()

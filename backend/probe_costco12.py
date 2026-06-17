"""
Probe 12 — harvest a LIVE client-identifier from the homepage's own gdx-api
traffic (homepage loads fine; CatalogSearch gets Akamai-blocked), then use it to
authorize the product summary API and inspect what grocery search terms actually
resolve to (names + prices + warehouse + delivery channel).

Answers definitively:
  A. Can we authorize the summary API with a freshly-harvested client-identifier?
  B. Do grocery terms ('milk','eggs',...) resolve to REAL grocery products with
     prices, or only to ship-to-home merchandise (frothers, chocolate, etc.)?

Run:  python probe_costco12.py
"""
import json, time, os

SEARCH_API  = "https://gdx-api.costco.com/catalog/search/api/v1/search"
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
CLIENT_ID   = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"

TERMS = ["milk", "eggs", "white rice", "olive oil", "coffee", "canned tuna"]

os.makedirs(".cache", exist_ok=True)
live = {"client_identifier": None, "sample_gdx_url": None, "summary_seen": []}


def main():
    from cloakbrowser import launch
    print("[probe12] Launching cloakbrowser ...")
    browser = launch(headless=True)
    ctx = browser.new_context()

    def on_request(req):
        if "gdx-api.costco.com" in req.url and not live["client_identifier"]:
            try:
                h = dict(req.all_headers())
            except Exception:
                h = dict(req.headers)
            cid = h.get("client-identifier")
            if cid:
                live["client_identifier"] = cid
                live["sample_gdx_url"] = req.url
                print(f"[probe12] LIVE client-identifier harvested: {cid}")

    def on_response(resp):
        # Capture any summary responses the homepage fires naturally (these 200 in
        # prior sessions) so we can confirm price fields & warehouse on real data.
        if "products/summary" in resp.url and resp.status == 200:
            try:
                data = json.loads(resp.text())
                live["summary_seen"].append(len(data.get("productData", [])))
            except Exception:
                pass

    page = ctx.new_page()
    page.on("request", on_request)
    page.on("response", on_response)

    print("[probe12] Warming homepage (fires gdx-api recommendations) ...")
    try:
        page.goto("https://www.costco.com/", wait_until="networkidle", timeout=60000)
    except Exception as e:
        print(f"[probe12] homepage: {e!r}")
    time.sleep(5)
    print(f"[probe12] Homepage title: {page.title()!r}")
    print(f"[probe12] Natural homepage summary responses (productData counts): {live['summary_seen']}")

    cid = live["client_identifier"]
    if not cid:
        print("[probe12] *** No live client-identifier harvested from homepage. ***")
        print("[probe12] The homepage fired no gdx-api XHR we could read. Cannot "
              "authorize summary API. Aborting.")
        page.close(); ctx.close(); browser.close()
        return

    headers = {
        "client-identifier": cid, "client_id": "USBC", "locale": "en-US",
        "searchresultprovider": "GRS", "content-type": "application/json",
        "accept": "*/*", "origin": "https://www.costco.com",
        "referer": "https://www.costco.com/",
    }

    out = {}
    for term in TERMS:
        body = {
            "visitorId": "83099816520155961790818054284274511765", "query": term,
            "pageSize": 24, "offset": 0, "searchMode": "page",
            "personalizationEnabled": False, "warehouseId": "347-wh",
            "shipToPostal": "46032", "shipToState": "IN", "deliveryLocations": ["347-wh"],
        }
        sr = ctx.request.fetch(SEARCH_API, method="POST", headers=headers,
                               data=json.dumps(body), timeout=30000)
        if sr.status != 200:
            print(f"  {term:13s}: search HTTP {sr.status}")
            out[term] = {"search_status": sr.status}
            continue
        ids = [r["id"] for r in json.loads(sr.text()).get("searchResult", {}).get("results", [])]
        sum_url = (f"{SUMMARY_API}?clientId={CLIENT_ID}"
                   f"&items={','.join(ids[:20])}&whsNumber=347&locales=en-us")
        sresp = ctx.request.get(sum_url, headers={k: v for k, v in headers.items()
                                                  if k != "content-type"}, timeout=30000)
        print(f"\n  === {term} ===  search ids={len(ids)}  summary HTTP {sresp.status}")
        if sresp.status != 200:
            print(f"      summary error: {sresp.text()[:140]}")
            out[term] = {"search_ids": len(ids), "summary_status": sresp.status}
            continue
        items = []
        for p in json.loads(sresp.text()).get("productData", []):
            name = ""
            for d in (p.get("descriptions") or []):
                if d.get("languageKey") == "en-US":
                    name = d.get("object", {}).get("shortDescription", "")
                    break
            best, whs = None, None
            for c in (p.get("childCatalogData") or []):
                dp = c.get("displayPrice")
                if dp and dp.get("onlinePrice"):
                    op = dp["onlinePrice"]
                    if best is None or op < best:
                        best, whs = op, dp.get("warehouseNumber")
            items.append({"id": p["id"], "name": name[:60], "price": best,
                          "whs": whs, "cartOnly": p.get("dispPriceInCartOnly")})
        out[term] = {"search_ids": len(ids), "returned": len(items), "items": items}
        for it in items[:8]:
            pr = f"${it['price']:8.2f}" if it["price"] else "   NO-PRICE"
            print(f"      {pr} whs={str(it['whs']):>4} cart={it['cartOnly']}  {it['name']}")

    with open(".cache/costco_probe12.json", "w") as f:
        json.dump({"client_identifier": cid, "results": out}, f, indent=2)
    print("\nSaved .cache/costco_probe12.json")

    page.close(); ctx.close(); browser.close()
    print("[probe12] Done.")


if __name__ == "__main__":
    main()

"""
Probe 13 — FINAL. Use in-page page.evaluate(fetch(...)) for BOTH search and
summary (the natural-context approach that beats Akamai, per the memory note).
Print the actual PRODUCT NAMES so we settle the real question:

  Does a Costco.com 'milk'/'eggs' search return real FRESH GROCERY,
  or only ship-to-home merchandise (frothers, chocolate, shelf-stable)?

Run:  python probe_costco13.py
"""
import json, time, os
os.makedirs(".cache", exist_ok=True)

SEARCH_API  = "https://gdx-api.costco.com/catalog/search/api/v1/search"
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
CLIENT_ID   = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
TERMS = ["milk", "eggs", "olive oil", "chicken breast"]


def main():
    from cloakbrowser import launch
    print("[probe13] Launching cloakbrowser ...")
    browser = launch(headless=True)
    ctx = browser.new_context()

    live_cid = {"v": None}
    def on_request(req):
        if "gdx-api.costco.com" in req.url and not live_cid["v"]:
            try:
                h = dict(req.all_headers())
            except Exception:
                h = dict(req.headers)
            if h.get("client-identifier"):
                live_cid["v"] = h["client-identifier"]

    page = ctx.new_page()
    page.on("request", on_request)
    print("[probe13] Warming homepage ...")
    try:
        page.goto("https://www.costco.com/", wait_until="networkidle", timeout=60000)
    except Exception as e:
        print(f"   homepage: {e!r}")
    time.sleep(5)
    cid = live_cid["v"] or "168287ea-1201-45f6-9b45-5bbea49f8ee7"
    print(f"[probe13] client-identifier: {cid}  homepage title={page.title()!r}")

    out = {}
    for term in TERMS:
        # In-page fetch for SEARCH (natural browser context, real TLS+cookies)
        search_js = """
        async (args) => {
          const [url, cid, term] = args;
          const body = {visitorId:"83099816520155961790818054284274511765", query:term,
            pageSize:24, offset:0, searchMode:"page", personalizationEnabled:false,
            warehouseId:"347-wh", shipToPostal:"46032", shipToState:"IN",
            deliveryLocations:["347-wh"]};
          try {
            const r = await fetch(url, {method:"POST", headers:{
              "client-identifier":cid, "client_id":"USBC", "locale":"en-US",
              "searchresultprovider":"GRS", "content-type":"application/json",
              "accept":"*/*"}, body: JSON.stringify(body)});
            const t = await r.text();
            return {status:r.status, body:t.substring(0,60000)};
          } catch(e){ return {status:0, body:String(e)}; }
        }"""
        sr = page.evaluate(search_js, [SEARCH_API, cid, term])
        if sr["status"] != 200:
            print(f"\n  === {term} ===  SEARCH in-page status {sr['status']}: {sr['body'][:120]}")
            out[term] = {"search_status": sr["status"]}
            continue
        sres = json.loads(sr["body"]).get("searchResult", {}).get("results", [])
        ids = [r["id"] for r in sres]
        # Pull any name/title already present in the search result
        def rname(r):
            for k in ("name", "title", "shortDescription"):
                if r.get(k): return r[k]
            a = r.get("attributes") or {}
            for k in ("item_name", "product_name", "name", "title"):
                if a.get(k): return a[k]
            p = r.get("product") or {}
            return p.get("name") or p.get("title") or "(no name in search result)"
        print(f"\n  === {term} ===  in-page SEARCH ok, {len(ids)} results")
        for r in sres[:10]:
            print(f"      [{r.get('id')}] {str(rname(r))[:70]}")

        # In-page fetch for SUMMARY (prices)
        summary_url = (f"{SUMMARY_API}?clientId={CLIENT_ID}"
                       f"&items={','.join(ids[:20])}&whsNumber=347&locales=en-us")
        summary_js = """
        async (args) => {
          const [url, cid] = args;
          try {
            const r = await fetch(url, {method:"GET", headers:{
              "client-identifier":cid, "client_id":"USBC", "locale":"en-US",
              "searchresultprovider":"GRS", "accept":"*/*"}});
            const t = await r.text();
            return {status:r.status, body:t.substring(0,120000)};
          } catch(e){ return {status:0, body:String(e)}; }
        }"""
        su = page.evaluate(summary_js, [summary_url, cid])
        if su["status"] != 200:
            print(f"      SUMMARY in-page status {su['status']}: {su['body'][:120]}")
            out[term] = {"search_ids": len(ids), "summary_status": su["status"],
                         "search_names": [str(rname(r))[:60] for r in sres[:10]]}
            continue
        prod = json.loads(su["body"]).get("productData", [])
        items = []
        for p in prod:
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
            items.append({"id": p["id"], "name": name[:60], "price": best, "whs": whs,
                          "cartOnly": p.get("dispPriceInCartOnly")})
        out[term] = {"search_ids": len(ids), "priced": len(items), "items": items}
        print(f"      --- summary prices ({len(items)}) ---")
        for it in items[:10]:
            pr = f"${it['price']:8.2f}" if it["price"] else "   NO-PRICE"
            print(f"      {pr} whs={str(it['whs']):>4} cart={it['cartOnly']}  {it['name']}")
        time.sleep(1)

    with open(".cache/costco_probe13.json", "w") as f:
        json.dump({"client_identifier": cid, "results": out}, f, indent=2)
    print("\nSaved .cache/costco_probe13.json")
    page.close(); ctx.close(); browser.close()
    print("[probe13] Done.")


if __name__ == "__main__":
    main()

"""
Costco probe 5 — capture ALL headers the browser sends on the search POST,
then replay it via ctx.request.fetch with those exact headers.

Run:  python probe_costco5.py
"""
import json
import time

HOME_URL = "https://www.costco.com/"
SEARCH_URL = "https://www.costco.com/CatalogSearch?keyword=milk&pageSize=24"
SEARCH_API = "https://gdx-api.costco.com/catalog/search/api/v1/search"
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
CLIENT_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"

captured_search_req = {}
captured_search_resp_ids: list[str] = []


def probe():
    from cloakbrowser import launch
    browser = launch(headless=True)
    ctx = browser.new_context()

    def on_request(req):
        if "catalog/search/api" in req.url:
            try:
                body = req.post_data or ""
            except Exception:
                body = ""
            captured_search_req.update({
                "method": req.method,
                "url": req.url,
                "all_headers": dict(req.all_headers()),   # includes cookies + pseudo-headers
                "body": body,
            })
            print(f"[probe5] Intercepted search request!")

    def on_response(resp):
        if "catalog/search/api" in resp.url and resp.status == 200:
            try:
                body = json.loads(resp.text())
                results = body.get("searchResult", {}).get("results", [])
                captured_search_resp_ids.extend([r["id"] for r in results[:12]])
                print(f"[probe5] Intercepted search response: {len(results)} results")
            except Exception as e:
                print(f"[probe5] Search response parse error: {e}")

    page = ctx.new_page()
    page.on("request", on_request)
    page.on("response", on_response)

    print("[probe5] Loading homepage ...")
    try:
        page.goto(HOME_URL, wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(3)

    print("[probe5] Loading search page ...")
    try:
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(5)

    print(f"\n=== Captured search request ===")
    if captured_search_req:
        print(f"Method: {captured_search_req['method']}")
        print(f"URL: {captured_search_req['url'][:100]}")
        print(f"Body: {captured_search_req['body'][:300]}")
        print(f"\nAll headers ({len(captured_search_req['all_headers'])}):")
        for k, v in sorted(captured_search_req["all_headers"].items()):
            # Mask cookie values
            if k.lower() == "cookie":
                print(f"  {k}: {v[:80]}... [truncated]")
            else:
                print(f"  {k}: {v}")
    else:
        print("  (no search request captured)")

    print(f"\n=== Replaying search request via ctx.request.fetch ===")
    if captured_search_req:
        # Replay with all captured headers
        headers = {k: v for k, v in captured_search_req["all_headers"].items()
                   if not k.startswith(":")}  # strip HTTP/2 pseudo-headers
        try:
            replay = ctx.request.fetch(
                SEARCH_API,
                method="POST",
                headers=headers,
                data=captured_search_req["body"],
                timeout=30000,
            )
            print(f"  Replay status: {replay.status}")
            if replay.status == 200:
                rb = json.loads(replay.text())
                ids = [r["id"] for r in rb.get("searchResult", {}).get("results", [])]
                print(f"  Replay product IDs ({len(ids)}): {ids[:8]}")
                captured_search_resp_ids.extend(ids)
                captured_search_resp_ids[:] = list(dict.fromkeys(captured_search_resp_ids))
            else:
                print(f"  Error: {replay.text()[:300]}")
        except Exception as e:
            print(f"  Error: {e}")
    else:
        print("  (no request to replay)")

    # Now fetch product summary with captured IDs
    if captured_search_resp_ids:
        print(f"\n=== Fetching product summary for {len(captured_search_resp_ids)} IDs ===")
        summary_url = (
            f"{SUMMARY_API}?clientId={CLIENT_ID}"
            f"&items={','.join(captured_search_resp_ids[:15])}"
            f"&whsNumber=347&locales=en-us"
        )
        print(f"URL: {summary_url[:120]}")
        sum_resp = ctx.request.get(summary_url, timeout=30000)
        print(f"Status: {sum_resp.status}")
        if sum_resp.status == 200:
            sum_body = json.loads(sum_resp.text())
            products = sum_body.get("productData", [])
            print(f"Products returned: {len(products)}")
            for p in products:
                name = ""
                for d in (p.get("descriptions") or []):
                    if d.get("languageKey") == "en-US":
                        name = d.get("object", {}).get("shortDescription", "")
                        break
                children = p.get("childCatalogData") or []
                price_info = []
                for c in children:
                    dp = c.get("displayPrice")
                    if dp:
                        price_info.append(f"online=${dp.get('onlinePrice')} whs={dp.get('warehouseNumber')}")
                print(f"  [{p['id']}] dispPriceInCartOnly={p.get('dispPriceInCartOnly'):1}  "
                      f"children={len(children)}  prices={price_info[:2] or 'NONE'}  "
                      f"{name[:50]}")

            # Save fixture
            with open(".cache/costco_milk_fixture.json", "w") as f:
                json.dump(products, f, indent=2)
            print(f"\nSaved fixture to .cache/costco_milk_fixture.json")
        else:
            print(f"Error: {sum_resp.text()[:300]}")

    page.close()
    ctx.close()
    browser.close()
    print("\n[probe5] Done.")


if __name__ == "__main__":
    probe()

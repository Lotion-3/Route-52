"""Capture ALL GraphQL operations to find the search step."""
import json, time, urllib.parse
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

OPERA_PATH = r"C:\Users\laksh\AppData\Local\Programs\Opera\opera.exe"
all_ops = []

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        executable_path=OPERA_PATH,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    page = ctx.new_page()
    Stealth().apply_stealth_sync(page)

    def on_request(req):
        if "graphql" not in req.url:
            return
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(req.url).query)
        op = qs.get("operationName", ["?"])[0]
        vars_raw = qs.get("variables", ["{}"])[0]
        try:
            variables = json.loads(vars_raw)
        except:
            variables = {}
        all_ops.append({"op": op, "url": req.url, "variables": variables, "headers": dict(req.headers)})
        print(f"  OP: {op}  vars_keys={list(variables.keys())}")

    page.on("request", on_request)

    page.goto("https://www.aldi.us/store/aldi/s?query=bananas", wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    for sel in ["button:has-text('Accept All')", "button:has-text('Accept')"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click(); time.sleep(2); print("Clicked cookies"); break
        except: pass

    for sel in ["text=Delivery", "a:has-text('Delivery')"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click(); time.sleep(3); print("Clicked Delivery"); break
        except: pass

    time.sleep(8)

    # Group by operation
    from collections import Counter
    ops = Counter(o["op"] for o in all_ops)
    print(f"\nOperations seen: {dict(ops)}")

    # Show non-Items operations
    search_ops = [o for o in all_ops if o["op"] not in ("Items",)]
    print(f"\nNon-Items ops ({len(search_ops)}):")
    for o in search_ops[:10]:
        print(f"  {o['op']}: keys={list(o['variables'].keys())}")
        if o['op'] not in ('', '?'):
            print(f"    URL snippet: {o['url'][50:150]}")

    with open("aldi_all_ops.json", "w") as f:
        json.dump(all_ops, f, indent=2)

    browser.close()

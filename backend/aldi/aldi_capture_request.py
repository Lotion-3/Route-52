"""
Capture the full GraphQL Items request (URL + headers + body) from ALDI.
Run this once to get the direct API call format.
"""
import json
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

OPERA_PATH = r"C:\Users\laksh\AppData\Local\Programs\Opera\opera.exe"
captured_requests = []

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        executable_path=OPERA_PATH,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    def on_request(request):
        if "graphql" in request.url and "operationName=Items" in request.url:
            captured_requests.append({
                "url": request.url,
                "method": request.method,
                "headers": dict(request.headers),
                "post_data": request.post_data,
            })
            print(f"\n[REQUEST CAPTURED] {request.method} {request.url[:120]}")

    page.on("request", on_request)

    print("Loading ALDI search...")
    page.goto("https://www.aldi.us/store/aldi/s?query=bananas", wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    # Accept cookies
    for sel in ["button:has-text('Accept All')", "button:has-text('Accept')"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                time.sleep(2)
                print("Clicked cookie accept")
                break
        except:
            pass

    # Click Delivery
    for sel in ["text=Delivery", "a:has-text('Delivery')", "div[role='button']:has-text('Delivery')", "li:has-text('Delivery')"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                time.sleep(3)
                print(f"Clicked Delivery: {sel}")
                break
        except:
            pass

    print("Waiting for GraphQL Items requests...")
    time.sleep(8)

    print(f"\nTotal requests captured: {len(captured_requests)}")
    if captured_requests:
        req = captured_requests[0]
        print(f"\nURL: {req['url']}")
        print(f"\nMethod: {req['method']}")
        print("\nHeaders:")
        for k, v in req["headers"].items():
            print(f"  {k}: {v[:80]}")
        with open("aldi_request_capture.json", "w") as f:
            json.dump(captured_requests, f, indent=2)
        print("\nSaved to aldi_request_capture.json")
    else:
        print("No Items requests captured!")
        # Dump all graphql requests
        page.on("request", lambda r: print(f"  REQ: {r.url[:100]}") if "graphql" in r.url else None)
        time.sleep(5)

    browser.close()

"""
Standalone Walmart cookie minter: launch CloakBrowser, warm PerimeterX via
home → search, harvest the cookie jar, and save to a JSON file.

Designed for one-at-a-time use or a batch of N sequential mints.

Usage:
    python mint_walmart_cookies.py                          # mint one, save to file
    python mint_walmart_cookies.py --count 5                # mint 5 cookies
    python mint_walmart_cookies.py --count 3 --proxy http://user:pass@ip:port
    python mint_walmart_cookies.py --headed                 # headed mode (debug)

Saved to: backend/.minted_walmart_cookies.json (JSON array, appended per run)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SEARCH_URL = "https://www.walmart.com/search?q={q}&affinityOverride=default&ps=40"
_WARM_URL = "https://www.walmart.com/"
_WARM_SEARCH_TERMS = (
    "eggs", "milk", "bread", "bananas", "chicken breast", "butter",
    "cheese", "rice", "coffee", "apples", "yogurt", "ground beef",
)
_OUTPUT = Path(__file__).parent / ".minted_walmart_cookies.json"
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}
_BLOCKED_DOMAIN_SUBSTRINGS = (
    "doubleclick", "googletagmanager", "google-analytics", "googlesyndication",
    "googleadservices", "facebook.com", "fbcdn", "fbevents", "adobedtm",
    "demdex", "everesttech", "tealiumiq", "omtrdc", "adsrvr", "tiktok",
    "bing.com/p", "clarity.ms", "hotjar", "criteo", "outbrain", "taboola",
    "spotxchange", "pinterest", "bat.bing",
)
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>')
_EXPLICIT_BLOCK_MARKERS = ("px-captcha",)


def _random_search_term() -> str:
    return random.choice(_WARM_SEARCH_TERMS)


def _has_explicit_block_marker(text: str) -> bool:
    return any(m in text.lower() for m in _EXPLICIT_BLOCK_MARKERS)


def _block_heavy_resources(ctx) -> None:
    def _handle(route):
        req = route.request
        url = req.url.lower()
        if req.resource_type in _BLOCKED_RESOURCE_TYPES or any(
            d in url for d in _BLOCKED_DOMAIN_SUBSTRINGS
        ):
            route.abort()
            return
        route.continue_()
    ctx.route("**/*", _handle)


def _wait_for_cookie(ctx, cookie_name: str, cap_seconds: float,
                      poll_interval: float = 0.15, settle_ticks: int = 2) -> bool:
    deadline = time.monotonic() + cap_seconds
    last_count = -1
    stable_ticks = 0
    while time.monotonic() < deadline:
        names = {c["name"] for c in ctx.cookies()}
        count = len(names)
        stable_ticks = stable_ticks + 1 if count == last_count else 0
        last_count = count
        if cookie_name in names and stable_ticks >= settle_ticks:
            return True
        time.sleep(poll_interval)
    return False


def mint_one(headless: bool = True, proxy: str | None = None,
             timeout: int = 60) -> dict | None:
    """Mint a single Walmart PerimeterX session.

    Returns {"cookies": {...}, "ua": "...", "saved_at_epoch": float,
             "saved_at_iso": str} on success, None on failure.
    """
    from cloakbrowser import launch

    kwargs: dict = {"headless": headless}
    if proxy:
        kwargs["proxy"] = proxy

    browser = launch(**kwargs)
    try:
        ctx = browser.new_context()
        _block_heavy_resources(ctx)
        page = ctx.new_page()

        page.goto(_WARM_URL, wait_until="domcontentloaded", timeout=45000)
        _wait_for_cookie(ctx, "_px3", cap_seconds=5)

        term = _random_search_term()
        page.goto(_SEARCH_URL.format(q=term), wait_until="domcontentloaded", timeout=45000)
        html = page.content()
        nd = page.evaluate(
            "() => { const e = document.getElementById('__NEXT_DATA__');"
            " return e ? e.textContent.length : 0; }"
        )
        ua = page.evaluate("() => navigator.userAgent")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    except Exception as e:
        print(f"  Browser error: {repr(e)[:120]}", flush=True)
        return None
    finally:
        try:
            browser.close()
        except Exception:
            pass

    if _has_explicit_block_marker(html):
        print(f"  Blocked by PerimeterX (px-captcha).", flush=True)
        return None
    if not nd or nd < 1000:
        print(f"  Weak warm — __NEXT_DATA__ only {nd} chars.", flush=True)
        return None

    now = time.time()
    return {
        "cookies": cookies,
        "ua": ua,
        "saved_at_epoch": now,
        "saved_at_iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
    }


def _load_existing() -> list[dict]:
    if _OUTPUT.exists():
        try:
            return json.loads(_OUTPUT.read_text())
        except Exception:
            pass
    return []


def _save(cookies: list[dict]) -> None:
    _OUTPUT.write_text(json.dumps(cookies, indent=2))
    print(f"\nSaved {len(cookies)} cookie(s) to {_OUTPUT}", flush=True)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Mint Walmart PerimeterX cookies")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of cookies to mint (default 1)")
    parser.add_argument("--headed", action="store_true",
                        help="Run browser in headed mode (visible)")
    parser.add_argument("--proxy", type=str, default=None,
                        help="Proxy URL (e.g. http://user:pass@ip:port)")
    parser.add_argument("--timeout", type=int, default=60,
                        help="Per-cookie timeout in seconds (default 60)")
    args = parser.parse_args()

    existing = _load_existing()
    total_before = len(existing)

    for i in range(args.count):
        label = f"[{i + 1}/{args.count}]"
        print(f"{label} Minting Walmart cookie...", flush=True)
        session = mint_one(headless=not args.headed, proxy=args.proxy,
                           timeout=args.timeout)
        if session:
            n = len(session["cookies"])
            has_px3 = "_px3" in session["cookies"]
            print(f"{label} OK — {n} cookies, px3={has_px3}", flush=True)
            existing.append(session)
        else:
            print(f"{label} FAILED", flush=True)
            if not args.count > 1:
                return 1

        if i < args.count - 1:
            delay = random.uniform(1.0, 3.0)
            print(f"  Waiting {delay:.1f}s before next mint...", flush=True)
            time.sleep(delay)

    _save(existing)
    new_count = len(existing) - total_before
    succeeded = sum(1 for s in existing[total_before:] if s)
    print(f"Minted {succeeded}/{args.count} new cookies (total in file: {len(existing)})")
    return 0 if succeeded == args.count else 1


if __name__ == "__main__":
    sys.exit(main())
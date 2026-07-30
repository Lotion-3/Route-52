"""
Health/TTL monitor: repeatedly replay ONE Walmart PerimeterX cookie at a fixed
interval and log latency + success/fail over time, until it dies (N
consecutive failures) or a max runtime is hit. Answers "exactly how long does
this cookie actually live, and does latency drift before it dies" -- rather
than the one-shot / burst checks in test_walmart_cookie_replay.py.

Deliberately standalone (no `import walmart_pricing`) -- same reasoning as
test_walmart_cookie_replay.py: keeps this runnable anywhere with just
curl_cffi, including as a GitHub Actions job later if useful.

Cookie source (checked in order):
  1. COOKIE_JSON env var -- explicit override (a "cookies" dict, as JSON)
  2. backend/.minted_walmart_cookies.json -- the LAST entry (most recently
     minted) unless COOKIE_INDEX picks a different one (1-based)

Every ping is appended as one JSON line to the log file, so a long-running
session's data survives a crash/Ctrl+C and can be reloaded later.

Env:
    COOKIE_JSON        optional explicit cookie dict (JSON). Overrides file.
    COOKIE_INDEX        1-based index into .minted_walmart_cookies.json
                         (default: last entry -- the freshest mint)
    SEARCH_TERM          search term to repeat each ping (default "milk").
                         Deliberately NOT named TERM -- that collides with
                         the shell's own $TERM (e.g. "xterm-256color").
    INTERVAL_SECONDS     seconds between pings (default 60)
    MAX_RUNTIME_SECONDS  give up after this long even if still alive
                         (default 14400 = 4h, comfortably past the ~1h
                         PerimeterX clearance this codebase assumes)
    STOP_AFTER_FAILS     consecutive failures before declaring it dead
                         (default 2 -- avoids calling one flaky blip "dead")
    LOG_FILE             JSONL output path (default
                         backend/.walmart_cookie_ttl_log.jsonl)

Usage:
    python monitor_walmart_cookie_ttl.py
    INTERVAL_SECONDS=30 python monitor_walmart_cookie_ttl.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import requests as ccffi

_SEARCH_URL = "https://www.walmart.com/search?q={q}&affinityOverride=default&ps=40"
_WARM_URL = "https://www.walmart.com/"
_COOKIE_FILE = Path(__file__).parent / ".minted_walmart_cookies.json"
_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0.0.0 Safari/537.36")
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>')
_EXPLICIT_BLOCK_MARKERS = ("px-captcha",)


def _has_explicit_block_marker(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in _EXPLICIT_BLOCK_MARKERS)


def _find_items(o) -> list:
    if isinstance(o, dict):
        if isinstance(o.get("itemStacks"), list):
            items: list = []
            for st in o["itemStacks"]:
                if isinstance(st, dict) and st.get("items"):
                    items.extend(st["items"])
            if items:
                return items
        for v in o.values():
            r = _find_items(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_items(v)
            if r:
                return r
    return []


def _ping(term: str, cookies: dict, ua: str) -> dict:
    """One replay. Returns a result dict (never raises -- transport errors
    are captured as a failed ping, not a crash)."""
    t0 = time.monotonic()
    url = _SEARCH_URL.format(q=term.replace(" ", "+"))
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": _WARM_URL,
        "user-agent": ua,
    }
    try:
        resp = ccffi.get(url, headers=headers, cookies=cookies,
                          impersonate="chrome", timeout=30)
    except Exception as e:
        return {"ok": False, "detail": f"transport error: {repr(e)[:100]}",
                "latency_ms": (time.monotonic() - t0) * 1000}

    latency_ms = (time.monotonic() - t0) * 1000
    if _has_explicit_block_marker(resp.text):
        return {"ok": False, "detail": f"BLOCKED (px-captcha) status={resp.status_code}",
                "latency_ms": latency_ms}

    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        return {"ok": False, "detail": f"BLOCKED (no __NEXT_DATA__) status={resp.status_code}",
                "latency_ms": latency_ms}

    try:
        items = _find_items(json.loads(m.group(1)))
    except Exception:
        items = []

    if items:
        return {"ok": True, "detail": f"{len(items)} products", "latency_ms": latency_ms}
    return {"ok": False, "detail": f"no products (status={resp.status_code})",
            "latency_ms": latency_ms}


def _load_cookie() -> tuple[dict, str, float | None]:
    """Returns (cookies, ua, minted_at_epoch_or_None)."""
    raw = os.environ.get("COOKIE_JSON", "")
    if raw:
        cookies = json.loads(raw)
        return cookies, os.environ.get("UA") or _DEFAULT_UA, None

    if not _COOKIE_FILE.exists():
        print(f"No cookie source: set COOKIE_JSON or create {_COOKIE_FILE}.", flush=True)
        sys.exit(1)
    sessions = json.loads(_COOKIE_FILE.read_text())
    if not sessions:
        print(f"{_COOKIE_FILE} is empty.", flush=True)
        sys.exit(1)

    idx_env = os.environ.get("COOKIE_INDEX")
    idx = int(idx_env) - 1 if idx_env else len(sessions) - 1
    if not (0 <= idx < len(sessions)):
        print(f"COOKIE_INDEX out of range (file has {len(sessions)} entries).", flush=True)
        sys.exit(1)

    s = sessions[idx]
    print(f"Using cookie #{idx + 1}/{len(sessions)} from {_COOKIE_FILE.name} "
          f"(minted {s.get('saved_at_iso', 'unknown')}, {len(s['cookies'])} cookies)",
          flush=True)
    return s["cookies"], s.get("ua") or _DEFAULT_UA, s.get("saved_at_epoch")


def main() -> int:
    cookies, ua, minted_at = _load_cookie()
    term = os.environ.get("SEARCH_TERM") or "milk"
    interval = float(os.environ.get("INTERVAL_SECONDS") or "60")
    max_runtime = float(os.environ.get("MAX_RUNTIME_SECONDS") or str(4 * 3600))
    stop_after_fails = int(os.environ.get("STOP_AFTER_FAILS") or "2")
    log_path = Path(os.environ.get("LOG_FILE") or str(Path(__file__).parent / ".walmart_cookie_ttl_log.jsonl"))

    start = time.monotonic()
    consecutive_fails = 0
    pings: list[dict] = []
    died_at_age_s: float | None = None

    print(f"Monitoring cookie every {interval:.0f}s, term={term!r}, "
          f"max runtime {max_runtime/60:.0f}min, stop after {stop_after_fails} "
          f"consecutive fails. Logging to {log_path}\n", flush=True)

    log_f = open(log_path, "a")
    try:
        while True:
            elapsed_since_start = time.monotonic() - start
            if elapsed_since_start > max_runtime:
                print(f"\nReached max runtime ({max_runtime/60:.0f}min) -- stopping "
                      f"(cookie was still alive).", flush=True)
                break

            now = time.time()
            cookie_age_s = (now - minted_at) if minted_at else None
            result = _ping(term, cookies, ua)
            result["ts_iso"] = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
            result["cookie_age_s"] = cookie_age_s
            pings.append(result)
            log_f.write(json.dumps(result) + "\n")
            log_f.flush()

            status = "OK  " if result["ok"] else "FAIL"
            age_str = f"age={cookie_age_s/60:5.1f}m" if cookie_age_s is not None else "age=unknown"
            print(f"[{result['ts_iso']}]  {status}  {age_str}  "
                  f"{result['latency_ms']:6.0f}ms  {result['detail']}", flush=True)

            if result["ok"]:
                consecutive_fails = 0
            else:
                consecutive_fails += 1
                if consecutive_fails >= stop_after_fails:
                    died_at_age_s = cookie_age_s
                    print(f"\n{consecutive_fails} consecutive failures -- declaring the "
                          f"cookie dead.", flush=True)
                    break

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nInterrupted by user.", flush=True)
    finally:
        log_f.close()

    _print_summary(pings, minted_at, died_at_age_s)
    return 0


def _print_summary(pings: list[dict], minted_at: float | None, died_at_age_s: float | None) -> None:
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY: {len(pings)} ping(s)")
    oks = [p for p in pings if p["ok"]]
    fails = [p for p in pings if not p["ok"]]
    print(f"  {len(oks)} succeeded, {len(fails)} failed")
    if oks:
        latencies = [p["latency_ms"] for p in oks]
        print(f"  Latency (successful pings): min={min(latencies):.0f}ms  "
              f"avg={sum(latencies)/len(latencies):.0f}ms  max={max(latencies):.0f}ms")
        first_half = latencies[: len(latencies) // 2] or latencies
        second_half = latencies[len(latencies) // 2:] or latencies
        print(f"  First-half avg={sum(first_half)/len(first_half):.0f}ms  "
              f"vs second-half avg={sum(second_half)/len(second_half):.0f}ms")
    if died_at_age_s is not None:
        print(f"  Cookie died at age {died_at_age_s/60:.1f} minutes "
              f"({died_at_age_s:.0f}s) since mint.")
    elif minted_at is not None and pings:
        last_age = pings[-1]["cookie_age_s"]
        print(f"  Cookie was still alive at age {last_age/60:.1f} minutes "
              f"when monitoring stopped.")
    print(f"  {'=' * 60}")


if __name__ == "__main__":
    sys.exit(main())

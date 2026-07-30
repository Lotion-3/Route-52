"""
Long-run Walmart cookie health monitor.

Self-contained: the cookie is baked in below (no env vars, no external files
needed) so this runs just by pressing "Run" in VS Code with zero setup. No
proxy -- goes direct from this machine's own IP.

Behavior:
  - Every CHECK_INTERVAL_SECONDS (10 min), fires BURST_SIZE (5) SIMULTANEOUS
    requests against the same cookie -- well under the confirmed-safe
    20-concurrency wall (see test_walmart_concurrency_matrix.py findings),
    so a failure here means the COOKIE is dead, not that the burst itself
    tripped the concurrency limit.
  - A check-in counts as OK if AT LEAST ONE of the 5 requests gets a real
    response; it counts as a FAILURE only if all 5 come back blocked/dead
    ("no response" from the cookie that round).
  - Runs for up to MAX_RUNTIME_SECONDS (10 hours), OR stops early once
    CONSECUTIVE_FAIL_LIMIT (5) check-ins in a row have failed -- i.e. the
    cookie is declared dead after ~5 * 10min with no response.
  - Every check-in is logged to LOG_FILE (plain text, human-readable, flushed
    immediately) AND printed to stdout, so you can read it live in VS Code's
    terminal or open the log file afterward.

Requires: curl_cffi (already a backend dependency). If VS Code's "Run"
button uses a different Python interpreter than the one with curl_cffi
installed (this project normally uses its Anaconda env), select that
interpreter first (bottom-right of VS Code, or Ctrl+Shift+P ->
"Python: Select Interpreter").

Usage: just press Run. No arguments needed.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from curl_cffi import requests as ccffi

# ---------------------------------------------------------------------------
# Config -- edit these if you want, but defaults match what was requested.
# ---------------------------------------------------------------------------
CHECK_INTERVAL_SECONDS = 10 * 60       # 10 minutes between check-ins
MAX_RUNTIME_SECONDS = 10 * 60 * 60     # 10 hours total
BURST_SIZE = 5                         # 5 simultaneous requests per check-in
CONSECUTIVE_FAIL_LIMIT = 5             # die after 5 check-ins in a row with zero responses
LOG_FILE = Path(__file__).parent / "walmart_10h_monitor_results.log"

# Existing pool cookie (backend/.minted_walmart_cookies.json, most recently
# minted entry as of 2026-07-30T02:30:41Z), reused as-is -- NOT freshly
# validated by a live request, since our local IP is currently blocked and
# no proxy is used to route around that. The script's own first check-in is
# the real test of whether this cookie is alive.
COOKIES = {"isoLoc": "GB_EN_t3", "ak_bmsc": "CE05EE603D48B03BD1C52E2A70A2EEE7~000000000000000000000000000000~YAAQktN6XP9MJaSfAQAABvXbsADgidy5yPtAeUI8Uh7xEpYyS0z0jxv4XpQGeLMVXKW2uL/WY6koIt7gAjuiWRre94f25Xxc5GzCW6G/KJ3Ngf2GLiUuy98nxaX2BYTn09nXj0l+wVPj7sHPlICkkylPe2Q9m3WBFujMDVkUr5FTy++K+S8oqm9Wz7FGB0lFCklexf5myEYW8/tRWBUI8rGGaz7/xdaODDQ1/fy/RHSkpZL9nWXidqQeW4gVEGgY9nQp3WKKa1ow3vTZD9AnaPRt0SVCC0mvr6O8R2YEO8EuIaEx9WPBubvOrI1D2b4J8kdg8nhRZRfKWbIiLZ/r/mESrHA8VJ7jq1UapR94uVGrtZ8D8ciZuDFBolBXv3WJD20UwWVo7jl0oVvA", "btc": "RhsnLpj9H82ZYlxHcb1edw", "bsc": "RhsnLpj9H82ZYlxHcb1edw", "b30msc": "RhsnLpj9H82ZYlxHcb1edw", "vtc": "RhsnLpj9H82ZYlxHcb1edw", "bstc": "RhsnLpj9H82ZYlxHcb1edw", "_astc": "3b80eb70ca9dc5d968326349165b9dbf", "_pxvid": "a48b3409-8bbe-11f1-9e24-04be076b4af2", "pxcts": "a48b3b41-8bbe-11f1-9e24-e65254dc8ecc", "adblocked": "true", "akavpau_p5": "1785379236~id=faa6bc6c828a873ee0f29e5ce28ab9ad", "_px3": "ab75bcf3ebce6e30afef852583ff3e80f216352aab6ed35723dd853a6763f527:CrTwUz4ogtGEb+fdrL6Q8+db2auFU3UA/U00nNb/AahozRxvKrmMGSsB5m1xF01Pauv96Ww/vYjr96IEOLjpTQ==:1000:WXQN+akWU5csDrijdJjy1rzAqnjHfL1HXusDXIG20pVR7kbwLSGFaqTEQyzpnUb2y5a+rnFR9t+2SPV+iDRflcojVJhbkDUERKPz7sViXw+kXSci+nMyK7zLPK8A+OTqWnnVUFFuBdTXox+rPLb3bGixzBJo6MY80yMjlVGCi5zB7mdda1PrUnUmJvL9wmGSyp4lDsd1RyHWt6GoCcBKG1lqkM9OKuOUF8LWKDBzUss5zbhs6Ol0cdnWy7I36Oen7HJB13B+FjPt22E9NNN1gvwWaZoSLn78RjCdymuJ8kb/FaRoPHZhafnvZ4AqCfLvy8NElyrfUpqTweDAY/Hv/1AKSn/H0E2EU1qbo4f+W5GGfds3GjKw2NdM/M4Wx0nTeOSTyMy4CJc5yQc/Yx8axGW7TdFVcENhsQHRLMK6tP2C24PfYA1TRjiUhePXEkXOO5dVussx6NAXAxyXIYAbgQ==", "abqme": "true", "xpth": "x-o-mart%2BB2C~x-o-mverified%2Bfalse", "xpa": "2D2F2|9dY_u|9oyCa|BMjDU|CA1jM|CSoDz|ESBus|Eb6Ic|FwNi-|GdZlx|HfIVM|J5DJU|J9IDU|KOgEP|L3B2Z|Ljsr_|PGIOp|ROrJ5|VqK1m|X1bNP|YDqSx|bmBIA|duYB9|jIKKp|jM1ax|lfM8p|pOxXm|pUcSK|t38VL|uUbzG|vj2ST|zaPbp|zxdKF", "exp-ck": "9dY_u19oyCa1CA1jM3CSoDz1FwNi-1GdZlx1HfIVM1J5DJU1J9IDU1KOgEP1L3B2Z1Ljsr_1ROrJ51VqK1m2X1bNP1bmBIA1jIKKp1lfM8p1pOxXm1pUcSK2t38VL1uUbzG1vj2ST2zaPbp1", "_pxhd": "564065658b0fc07fb4c410594f5d4756f7031b7a12081d6552595b7ce808c44a:a48b3409-8bbe-11f1-9e24-04be076b4af2", "AID": "wmlspartner=0:reflectorid=0000000000000000000000:lastupd=1785378637251", "com.wm.reflector": "reflectorid:0000000000000000000000@lastupd:1785378637251@firstcreate:1785378637251", "ACID": "55d9f5d8-5f02-4856-bb43-1ea071c118ca", "_m": "9", "hasACID": "true", "userAppVersion": "usweb-1.289.0-8c815de0c0c175097bdbb457fdaf6425489ba7e5-7281416r", "xpm": "1%2B1785378636%2BRhsnLpj9H82ZYlxHcb1edw~%2B0", "xptwg": "2816283005:8646F0A7B2C838:1430585:877B6B65:1335252F:F7E98445:", "xptwj": "uz:661e8502e0be0d14a788:Lkl3p5tGEf4bsb3uR1NcWagOdVbRaBcdVrwFhGaEVRynl3fr9KNb+8S42q09FROT2ioufr49F6OBvS/F4iYToEQnFbwDclngeg+Y8Zv6n9Iz4NUVZ+8C5hYEKgclkq+iR70C6alVlGd+IDGP5pP3owqfzftxRFxTwruv+p05", "TS012768cf": "0123bc276c488c6e50082639e2e847aa435b7c553dbcb74fb6bbbd0984849f894d99c6664cc88ce86e78e0ebfe59e24769f22fef4e", "TS01a90220": "0123bc276c488c6e50082639e2e847aa435b7c553dbcb74fb6bbbd0984849f894d99c6664cc88ce86e78e0ebfe59e24769f22fef4e", "TS2a5e0c5c027": "08d5433fccab200097480944440dbe6ed92b8dad53f114eab5c2a049079a0bba935b62f75fa9334508839785621130007aac4a3ff8a51166feddd385ab180e410b04ec4f237459ffa9c46c2821a81cf96dd905266c021b707b9659adea1b2f68", "akavpau_p2": "1785379239~id=5c7c2f210f341ff44af5b66ffbad2db0", "bm_mi": "B93BA8714D43BA3C87B9E0B683F81F1E~YAAQktN6XF5OJaSfAQAAdg7csADdyiaMv9GyzwThrZf4DOrHKL/95Q8kdr2vN3FZq/Dhf5feWBlOcbOhw2MrhkjIdQ8/q+47oDaPNuRm0H5iV7jE20UMkctf3gofm0LcsdVSgf0+J50bNPTBOcFiJedREsOmxsSR3ytxCu42WFX8IrzSfadX3F1Tdfn3oaAJSNulRuoCbZhJeEwuNwur0vWPcW5ew3Ulv6/3ZCWxuwZWqaZQFPsvEgVsqGrjSIslwVTDeVdb9eVAnWXPcRMR6hPuc1QdCjzYBL39rXe0GV2EUn0sDQ7iWt75bKTgLwUdupi1rg==~1", "bm_sv": "52EC746FA99052F9D2D95480DC95BFFB~YAAQktN6XF9OJaSfAQAAdg7csABUMJ9A1ugi/srjKP7Kho2mXqRf6kwYbi/SeY85iBV+9gmvD+0Y2bO6AuaC9xbnoiAqiKFhtzqlvInoh/MlgviKNyUg/VS5ZmvKsNGAuPPM/e1c3MLQ2t3L8FGlrR3I/UAQ/zxYKZvW+c0pWTJiO51SHdiHEmk1XPoJ9z0UN7m5+SCpI4Hor99ucGy2cDKWU9GBcqs45f/OUctjjIXWSOxSBlPKqIAiCiGso0S3eA==~1", "_pxde": "d15f5749abb867875047fd2bbebab43c5b3f3c949bbb6f3a83d374ac5d357b75:eyJ0aW1lc3RhbXAiOjE3ODUzNzg2NDAzMDIsImZfa2IiOjAsImlwY19pZCI6W10sImluY19pZCI6WyIxYjFkNGZjM2E0NGY5NjI0MDc5YWQ3NWQyNzg1MWY1YSIsImEyNDY3MTdmOTFhOTBkNWYzZDQ0YjE5ZDRhNTlkNjNjIl19"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

# No proxy -- goes direct from this machine. Note: this machine's IP was
# confirmed blocked by Walmart earlier in this session (from deliberate
# over-the-concurrency-wall testing); if that hasn't cleared yet, check-ins
# will fail regardless of the cookie's own health until it does.
PROXY = None

_GROCERY_TERMS = [
    "milk", "eggs", "bread", "bananas", "chicken breast", "butter",
    "cheese", "rice", "coffee", "apples", "yogurt", "ground beef",
    "spinach", "pasta", "tomatoes", "onions",
]
_SEARCH_URL = "https://www.walmart.com/search?q={q}&affinityOverride=default&ps=10"


def _hit(term: str) -> dict:
    t0 = time.monotonic()
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": "https://www.walmart.com/",
        "user-agent": UA,
    }
    try:
        kwargs = dict(headers=headers, cookies=COOKIES, impersonate="chrome", timeout=30)
        if PROXY:
            kwargs["proxy"] = PROXY
        resp = ccffi.get(_SEARCH_URL.format(q=quote_plus(term)), **kwargs)
    except Exception as e:
        return {"term": term, "ok": False, "detail": f"transport error: {repr(e)[:100]}",
                "elapsed": time.monotonic() - t0}
    elapsed = time.monotonic() - t0
    if "px-captcha" in resp.text.lower():
        return {"term": term, "ok": False, "detail": f"BLOCKED (px-captcha) status={resp.status_code}",
                "elapsed": elapsed}
    if "__NEXT_DATA__" not in resp.text:
        return {"term": term, "ok": False, "detail": f"no __NEXT_DATA__ status={resp.status_code}",
                "elapsed": elapsed}
    return {"term": term, "ok": True, "detail": "OK", "elapsed": elapsed}


def _log(line: str, f) -> None:
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main() -> None:
    start = time.monotonic()
    consecutive_fails = 0
    check_num = 0

    with open(LOG_FILE, "a") as f:
        _log(f"\n{'=' * 70}", f)
        _log(f"Walmart 10-hour cookie monitor starting {datetime.now(timezone.utc).isoformat()}", f)
        _log(f"Check every {CHECK_INTERVAL_SECONDS // 60}min, burst={BURST_SIZE}, "
             f"max runtime {MAX_RUNTIME_SECONDS // 3600}h, dies after "
             f"{CONSECUTIVE_FAIL_LIMIT} consecutive failed check-ins.", f)
        _log(f"Logging to {LOG_FILE}", f)
        _log(f"{'=' * 70}\n", f)

        try:
            while True:
                elapsed_total = time.monotonic() - start
                if elapsed_total > MAX_RUNTIME_SECONDS:
                    _log(f"\nReached max runtime ({MAX_RUNTIME_SECONDS / 3600:.1f}h) — "
                         f"stopping. Cookie was still alive.", f)
                    break

                check_num += 1
                now = datetime.now(timezone.utc).isoformat()
                terms = [_GROCERY_TERMS[(check_num * BURST_SIZE + i) % len(_GROCERY_TERMS)]
                         for i in range(BURST_SIZE)]

                results = []
                with ThreadPoolExecutor(max_workers=BURST_SIZE) as pool:
                    futs = [pool.submit(_hit, t) for t in terms]
                    for fut in as_completed(futs):
                        results.append(fut.result())

                ok_count = sum(1 for r in results if r["ok"])
                check_ok = ok_count > 0  # "no response" only if ALL 5 failed
                status = "OK" if check_ok else "FAIL"

                detail_str = ", ".join(f"{r['term']}={'ok' if r['ok'] else r['detail']}" for r in results)
                _log(f"[{now}] check #{check_num:3d} (age={elapsed_total/60:6.1f}min)  "
                     f"{status}  {ok_count}/{BURST_SIZE} responded  |  {detail_str}", f)

                if check_ok:
                    consecutive_fails = 0
                else:
                    consecutive_fails += 1
                    _log(f"    -> {consecutive_fails}/{CONSECUTIVE_FAIL_LIMIT} consecutive "
                         f"failed check-ins.", f)
                    if consecutive_fails >= CONSECUTIVE_FAIL_LIMIT:
                        _log(f"\n{consecutive_fails} consecutive failed check-ins "
                             f"({consecutive_fails * CHECK_INTERVAL_SECONDS / 60:.0f} min with no "
                             f"response) — declaring the cookie dead at age "
                             f"{elapsed_total/60:.1f} minutes.", f)
                        break

                time.sleep(CHECK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            _log("\nInterrupted by user.", f)

        _log(f"\nFinished after {check_num} check-in(s), "
             f"{(time.monotonic() - start)/60:.1f} minutes total.", f)
        _log(f"{'=' * 70}\n", f)


if __name__ == "__main__":
    main()

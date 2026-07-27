"""
Shared CloakBrowser gate — lets the browser-based chains run on a 512MB host.

The out-of-memory problem was never one browser; it was CONCURRENCY. Nothing
coordinated browsers across chains, so the eager prewarm launched 2 at once,
generate_plan's fan-out launched 4+, and Walmart's pool launched up to 6 — each
~200-700MB. This module fixes that three ways, without restructuring any chain:

  1. A process-global gate so only ONE CloakBrowser is ever alive at a time.
     `launch()` acquires it; the returned handle releases it on `.close()`.
     Every chain already does launch -> use -> close (with try/finally), so
     just swapping `from cloakbrowser import launch` to `from browser_gate
     import launch` serializes all of them automatically. Non-browser chains
     (Kroger API, Meijer/IGA via curl_cffi) keep running concurrently; the
     browser chains simply queue on the gate.

  2. Low-memory Chrome flags merged into every launch. Validated 2026-07-25:
     these still clear Imperva/Akamai (reese84 / _abck are still minted), so
     they don't break the WAF pass. `--disable-dev-shm-usage` is the critical
     one — in a container /dev/shm defaults to 64MB and Chrome crashes when it
     fills, which looks exactly like an OOM.

  3. A LEASE, not a bare lock. A plain lock made a single leaked browser
     (one chain missing a try/finally, one browser kept alive across requests)
     deadlock every browser chain for the life of the process — the failure
     this module was supposed to prevent. Each acquisition now carries an
     expiring lease: a holder that exceeds BROWSER_GATE_MAX_HOLD is reclaimed
     by the next waiter, and its stale `.close()` is ignored via a fencing
     token so it can never free someone else's lease.

Combined with the existing 20-minute cookie disk-cache (a browser only launches
on a cache miss, ~once per chain per 20 min) and the image/font/ad-tech
blocking already in the warms, peak RSS stays to one lean browser.

Env:
  LOW_MEMORY_MODE=0        disable the low-mem flags (keep the serialization)
  BROWSER_SINGLE_PROCESS=1 add --single-process (biggest memory cut, but can
                           destabilize the WAF JS challenge — opt-in only)
  BROWSER_GATE_TIMEOUT     seconds to wait for the gate before giving up
                           (default 45).
  BROWSER_GATE_MAX_HOLD    seconds one holder may keep the gate before a
                           waiter may reclaim it (default 180). The backstop
                           for a leaked or long-lived browser.
"""
from __future__ import annotations

import os
import threading
import time

_LOWMEM = os.environ.get("LOW_MEMORY_MODE", "1") != "0"
# 45s (was 180): with browsers serialized one-at-a-time, a chain waiting on the
# gate should give up FAST and fall back (Instacart / cached / skip) rather than
# stall the whole plan request for minutes while earlier browser chains grind
# through on a slow host. Observed in prod: ALDI waited the full 180s behind
# Walmart's warm and timed out anyway — better to bail at 45s and move on.
_GATE_TIMEOUT = float(os.environ.get("BROWSER_GATE_TIMEOUT", "45"))
# Backstop for a leaked/abandoned browser. Comfortably longer than a healthy
# warm (homepage + search nav, two 45s page timeouts) so we never reclaim a
# browser that is merely slow, but short enough that a leak self-heals rather
# than bricking every browser chain until restart.
_MAX_HOLD = float(os.environ.get("BROWSER_GATE_MAX_HOLD", "180"))

# Validated to still clear Imperva/Akamai. --disable-dev-shm-usage is essential
# in containers; the site-per-process disable + renderer cap collapse Chrome's
# multi-renderer memory; the V8 heap cap bounds the JS challenge's allocation.
_BASE_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-features=site-per-process,TranslateUI",
    "--renderer-process-limit=1",
    "--js-flags=--max-old-space-size=256",
    "--no-first-run",
    "--no-default-browser-check",
]
if os.environ.get("BROWSER_SINGLE_PROCESS") == "1":
    _BASE_ARGS.append("--single-process")


class GateTimeout(RuntimeError):
    """Raised when the browser gate can't be acquired within BROWSER_GATE_TIMEOUT.

    Callers should treat this as "no browser available right now" and fall back
    (cached cookie / Instacart / skip the store) — NOT retry `launch()`, which
    would just wait out the timeout a second time.
    """


# Backwards-compatible alias (the old private name).
_GateTimeout = GateTimeout


# ── The lease ───────────────────────────────────────────────────────────────
# _cv guards _holder. _holder is None (free) or a dict describing the current
# lease: {"token": int, "thread": str, "since": float}. The fencing token makes
# a stale release a no-op, so a reclaimed holder closing late can never free the
# lease belonging to whoever took it over.

_cv = threading.Condition()
_holder: dict | None = None
_next_token = 0


def _acquire(timeout: float) -> int:
    """Take the gate, reclaiming an over-held lease if necessary. Returns the
    fencing token for this acquisition. Raises GateTimeout on failure."""
    global _holder, _next_token
    deadline = time.monotonic() + timeout
    with _cv:
        while True:
            if _holder is None:
                _next_token += 1
                _holder = {
                    "token": _next_token,
                    "thread": threading.current_thread().name,
                    "since": time.monotonic(),
                }
                return _next_token

            held_for = time.monotonic() - _holder["since"]
            if held_for > _MAX_HOLD:
                # The holder blew past the max hold — assume it leaked (missing
                # close, crashed thread, browser kept alive across requests) and
                # reclaim. Its token is now stale, so its eventual close() is a
                # no-op rather than a release of OUR lease.
                print(
                    f"[browser_gate] Reclaiming gate from {_holder['thread']!r} "
                    f"after {held_for:.0f}s (> {_MAX_HOLD:.0f}s max hold) — "
                    f"the previous browser leaked or outlived its request.",
                    flush=True,
                )
                _holder = None
                continue

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GateTimeout(
                    f"gate held by {_holder['thread']!r} for {held_for:.0f}s; "
                    f"waited {timeout:.0f}s"
                )
            # Wake up at the earlier of our deadline and the holder's max-hold
            # expiry, so a leak is reclaimed promptly instead of at the next
            # release (which may never come).
            _cv.wait(timeout=min(remaining, max(0.05, _MAX_HOLD - held_for)))


def _release(token: int) -> None:
    """Free the gate if `token` still owns it; a stale token is ignored."""
    global _holder
    with _cv:
        if _holder is not None and _holder["token"] == token:
            _holder = None
            _cv.notify()


def gate_status() -> dict:
    """Introspection for health checks / debugging."""
    with _cv:
        if _holder is None:
            return {"held": False}
        return {
            "held": True,
            "thread": _holder["thread"],
            "held_for_seconds": round(time.monotonic() - _holder["since"], 1),
            "max_hold_seconds": _MAX_HOLD,
        }


class _GatedBrowser:
    """Transparent proxy around a CloakBrowser that releases the global gate when
    the browser is closed. Delegates every other attribute to the real browser."""

    def __init__(self, browser, token: int):
        self.__dict__["_browser"] = browser
        self.__dict__["_token"] = token

    def __getattr__(self, name):
        return getattr(self.__dict__["_browser"], name)

    def close(self, *a, **k):
        try:
            return self.__dict__["_browser"].close(*a, **k)
        finally:
            _release(self.__dict__["_token"])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def launch(**kwargs):
    """cloakbrowser.launch, but: (1) merges low-memory Chrome flags, and (2)
    holds a process-global lease until the returned browser is .close()'d, so
    only one browser is ever alive.

    Raises GateTimeout if no browser became available within
    BROWSER_GATE_TIMEOUT. A holder that exceeds BROWSER_GATE_MAX_HOLD is
    reclaimed automatically, so a leaked browser degrades one request instead
    of every request for the life of the process.

    ALWAYS close in a `finally` (or use `with`) — the gate is only freed by
    `.close()`, and until the max-hold backstop fires every other browser chain
    is blocked behind you.
    """
    from cloakbrowser import launch as _launch

    if _LOWMEM:
        kwargs["args"] = list(_BASE_ARGS) + list(kwargs.get("args") or [])

    token = _acquire(_GATE_TIMEOUT)
    try:
        return _GatedBrowser(_launch(**kwargs), token)
    except BaseException:
        _release(token)
        raise


def launch_geoip_optional(**kwargs):
    """`launch()`, retrying once WITHOUT the `geoip` flag if the first attempt
    fails — some cloakbrowser/proxy combinations reject `geoip=True`.

    Every proxied chain hand-rolled this retry as

        try:    browser = launch(**kwargs)
        except: kwargs.pop("geoip", None); browser = launch(**kwargs)

    which also retried on GateTimeout — paying the 45s wait a SECOND time
    (90s against a 75s pricing budget) for a condition a retry can never fix.
    This helper never retries a GateTimeout.
    """
    try:
        return launch(**kwargs)
    except GateTimeout:
        raise  # a retry would just wait out the timeout again
    except Exception:
        if "geoip" not in kwargs:
            raise
        kwargs.pop("geoip", None)
        return launch(**kwargs)

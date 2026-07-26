"""
Shared CloakBrowser gate — lets the browser-based chains run on a 512MB host.

The out-of-memory problem was never one browser; it was CONCURRENCY. Nothing
coordinated browsers across chains, so the eager prewarm launched 2 at once,
generate_plan's fan-out launched 4+, and Walmart's pool launched up to 6 — each
~200-700MB. This module fixes that two ways, without restructuring any chain:

  1. A process-global lock so only ONE CloakBrowser is ever alive at a time.
     `launch()` acquires it; the returned handle releases it on `.close()`.
     Every chain already does launch -> use -> close (with try/finally), so
     just swapping `from cloakbrowser import launch` to `from browser_gate
     import launch` serializes all of them automatically. Non-browser chains
     (Kroger API, Meijer/IGA via curl_cffi) keep running concurrently; the
     browser chains simply queue on the lock.

  2. Low-memory Chrome flags merged into every launch. Validated 2026-07-25:
     these still clear Imperva/Akamai (reese84 / _abck are still minted), so
     they don't break the WAF pass. `--disable-dev-shm-usage` is the critical
     one — in a container /dev/shm defaults to 64MB and Chrome crashes when it
     fills, which looks exactly like an OOM.

Combined with the existing 20-minute cookie disk-cache (a browser only launches
on a cache miss, ~once per chain per 20 min) and the image/font/ad-tech
blocking already in the warms, peak RSS stays to one lean browser.

Env:
  LOW_MEMORY_MODE=0        disable the low-mem flags (keep the serialization)
  BROWSER_SINGLE_PROCESS=1 add --single-process (biggest memory cut, but can
                           destabilize the WAF JS challenge — opt-in only)
  BROWSER_GATE_TIMEOUT     seconds to wait for the lock before giving up
                           (default 180); prevents a leaked browser deadlocking
                           the whole app.
"""
from __future__ import annotations

import os
import threading

_LOWMEM = os.environ.get("LOW_MEMORY_MODE", "1") != "0"
_GATE_TIMEOUT = float(os.environ.get("BROWSER_GATE_TIMEOUT", "180"))

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

# Process-global: at most one CloakBrowser alive at a time, across every chain.
_browser_lock = threading.Lock()


class _GateTimeout(RuntimeError):
    """Raised when the browser lock can't be acquired within BROWSER_GATE_TIMEOUT."""


class _GatedBrowser:
    """Transparent proxy around a CloakBrowser that releases the global lock when
    the browser is closed. Delegates every other attribute to the real browser."""

    def __init__(self, browser):
        self.__dict__["_browser"] = browser
        self.__dict__["_released"] = False

    def __getattr__(self, name):
        return getattr(self.__dict__["_browser"], name)

    def _release(self) -> None:
        if not self.__dict__["_released"]:
            self.__dict__["_released"] = True
            try:
                _browser_lock.release()
            except RuntimeError:
                pass

    def close(self, *a, **k):
        try:
            return self.__dict__["_browser"].close(*a, **k)
        finally:
            self._release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def launch(**kwargs):
    """cloakbrowser.launch, but: (1) merges low-memory Chrome flags, and (2)
    holds a process-global lock until the returned browser is .close()'d, so
    only one browser is ever alive. Raises _GateTimeout if another browser is
    held longer than BROWSER_GATE_TIMEOUT (guards against a leaked browser)."""
    from cloakbrowser import launch as _launch

    if _LOWMEM:
        kwargs["args"] = list(_BASE_ARGS) + list(kwargs.get("args") or [])

    if not _browser_lock.acquire(timeout=_GATE_TIMEOUT):
        raise _GateTimeout(
            f"another CloakBrowser held the gate > {_GATE_TIMEOUT}s")
    try:
        return _GatedBrowser(_launch(**kwargs))
    except Exception:
        try:
            _browser_lock.release()
        except RuntimeError:
            pass
        raise

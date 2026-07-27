"""
Shared, bounded execution for the per-store pricing fan-out.

Why this exists
───────────────
generate_plan used to build a fresh ThreadPoolExecutor per request and end with

    pool.shutdown(wait=False, cancel_futures=True)

`cancel_futures` only drops futures that have not STARTED. Every chain already
running kept going after the request gave up on it — still driving a browser,
still holding the process-global browser gate, still hammering the retailer.
Nothing bounded how many of those could pile up, so under repeated requests the
abandoned work multiplied: thread growth on a 512MB host, faster WAF bans, and
a browser gate held by a request that had already returned.

Three mechanisms fix that:

  1. ONE process-wide pool instead of one per request, so total pricing
     concurrency has a ceiling no matter how many requests arrive.

  2. SINGLE-FLIGHT per chain. A chain that is still running from an earlier
     (possibly abandoned) request is not started again — the new request skips
     it rather than stacking a second copy. Since there are only ~13 distinct
     chains, this is what actually bounds in-flight work: at most one run per
     chain, ever.

  3. A COOPERATIVE DEADLINE. Chains with a per-ingredient loop can call
     `time_left()` / `expired()` and stop early once the request that started
     them has given up, instead of grinding through the remaining basket for
     nobody. The deadline is published on a thread-local so chains can consult
     it without threading a parameter through ten call signatures.

None of this can abort a thread blocked inside a socket read — Python has no
safe thread kill. It bounds the damage instead: abandoned work is capped at one
run per chain and stops at the next cooperative checkpoint.

Env:
  PRICING_MAX_THREADS   ceiling on concurrent pricing threads (default 24)
"""
from __future__ import annotations

import functools
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

_MAX_THREADS = int(os.environ.get("PRICING_MAX_THREADS", "24"))

# One pool for the whole process. Never shut down — it outlives any single
# request on purpose, so an overrunning chain occupies a bounded slot instead
# of a thread nobody is counting.
_POOL = ThreadPoolExecutor(max_workers=_MAX_THREADS, thread_name_prefix="pricing")

# Chains currently executing, by key. Guarded by _inflight_lock.
_inflight: set[str] = set()
_inflight_lock = threading.Lock()

# The deadline governing the current worker thread, if any.
_local = threading.local()


class Deadline:
    """A monotonic wall-clock budget shared by one request's fan-out."""

    __slots__ = ("_end", "_budget")

    def __init__(self, seconds: float):
        self._budget = float(seconds)
        self._end = time.monotonic() + self._budget

    @property
    def budget(self) -> float:
        return self._budget

    def remaining(self) -> float:
        """Seconds left; never negative."""
        return max(0.0, self._end - time.monotonic())

    def expired(self) -> bool:
        return time.monotonic() >= self._end


# ── Cooperative deadline, visible to any code running on a pool thread ───────

def current_deadline() -> Optional[Deadline]:
    """The Deadline for the chain running on this thread, or None."""
    return getattr(_local, "deadline", None)


def time_left(default: float = float("inf")) -> float:
    """Seconds remaining in this thread's budget; `default` when unbudgeted."""
    d = current_deadline()
    return d.remaining() if d is not None else default


def expired() -> bool:
    """True once this thread's request has given up waiting. Long per-item
    loops should check this between items and bail out."""
    d = current_deadline()
    return d is not None and d.expired()


def bind_current_deadline(fn: Callable) -> Callable:
    """Wrap `fn` so it runs with the CALLING thread's deadline installed on
    whichever thread executes it.

    The deadline lives on a thread-local, so a chain that hands work to its own
    nested ThreadPoolExecutor (Trader Joe's, Instacart) would otherwise run
    those workers with no deadline at all — exactly the loops that most need to
    stop early. Wrap the callable at submit time to carry it across.
    """
    d = current_deadline()

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        prev = getattr(_local, "deadline", None)
        _local.deadline = d
        try:
            return fn(*args, **kwargs)
        finally:
            _local.deadline = prev

    return _wrapped


# ── Submission ──────────────────────────────────────────────────────────────

def _run(key: str, deadline: Optional[Deadline], fn: Callable, args, kwargs):
    _local.deadline = deadline
    try:
        return fn(*args, **kwargs)
    finally:
        _local.deadline = None
        with _inflight_lock:
            _inflight.discard(key)


def submit_chain(
    key: str,
    deadline: Optional[Deadline],
    fn: Callable,
    *args,
    **kwargs,
) -> Optional[Future]:
    """Run `fn` on the shared pool under `key`'s single-flight guard.

    Returns the Future, or None if a run for `key` is already in flight (in
    which case the caller should treat the chain as unavailable for this
    request — do NOT wait on the older run, it belongs to someone else).
    """
    with _inflight_lock:
        if key in _inflight:
            return None
        _inflight.add(key)
    try:
        return _POOL.submit(_run, key, deadline, fn, args, kwargs)
    except BaseException:
        # Submission itself failed (pool shutting down) — don't strand the key.
        with _inflight_lock:
            _inflight.discard(key)
        raise


def busy_chains() -> set[str]:
    """Snapshot of chains currently executing — for logging / health checks."""
    with _inflight_lock:
        return set(_inflight)


def stats() -> dict:
    with _inflight_lock:
        running = sorted(_inflight)
    return {"max_threads": _MAX_THREADS, "in_flight": running, "count": len(running)}

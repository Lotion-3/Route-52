import json
import os
import hashlib
import tempfile
import threading
import time
from collections import OrderedDict
from typing import Any, Optional


class CacheManager:
    """File-backed cache with an in-memory layer on top.

    Hot keys (geocode, isochrone, store search) are read many times per request;
    the in-memory layer serves those without re-reading + re-parsing JSON from
    disk. Disk writes are atomic (temp file + os.replace) and guarded by a lock so
    the concurrent per-store pricing fan-out can't interleave a half-written file.
    The disk tier keeps the cache warm across process restarts (prewarm primes it,
    generate_plan reads it).
    """

    # Disk tier bounds. The disk tier had NO eviction at all: every distinct
    # geocode / isochrone / store-search / matrix key wrote a file that lived
    # forever, so a long-running deploy accumulated one per coordinate it ever
    # saw. Entries older than the max age are swept, and if the directory is
    # still over the file cap the oldest are dropped.
    DISK_MAX_FILES = int(os.environ.get("CACHE_MAX_FILES", "5000"))
    DISK_MAX_AGE_SECONDS = int(os.environ.get("CACHE_MAX_AGE_SECONDS", str(30 * 86400)))
    _SWEEP_EVERY = 200  # writes between sweeps

    def __init__(self, cache_dir: Optional[str] = None, mem_max: int = 512):
        # Anchor to this file's directory unless told otherwise. A bare ".cache"
        # resolved against the process CWD, so launching the server from the
        # repo root vs. backend/ silently used two different caches.
        self.cache_dir = cache_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
        self._mem: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._mem_max = mem_max
        self._lock = threading.Lock()
        self._writes_since_sweep = 0
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_path(self, key_str: str) -> str:
        hash_key = hashlib.md5(key_str.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{hash_key}.json")

    @staticmethod
    def _fresh(cached_time: float, max_age_seconds: Optional[int]) -> bool:
        return max_age_seconds is None or (time.time() - cached_time) < max_age_seconds

    def get(self, key_data: Any, max_age_seconds: Optional[int] = None) -> Optional[Any]:
        """Return cached data if present and within max_age, else None."""
        key_str = json.dumps(key_data, sort_keys=True)
        hash_key = hashlib.md5(key_str.encode("utf-8")).hexdigest()

        # Fast path: in-memory.
        with self._lock:
            hit = self._mem.get(hash_key)
            if hit is not None:
                ts, data = hit
                if self._fresh(ts, max_age_seconds):
                    self._mem.move_to_end(hash_key)  # LRU touch
                    return data

        # Slow path: disk, then populate memory.
        cache_path = os.path.join(self.cache_dir, f"{hash_key}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    entry = json.load(f)
            except Exception:
                return None
            ts = entry.get("timestamp", 0)
            if self._fresh(ts, max_age_seconds):
                data = entry.get("data")
                self._remember(hash_key, ts, data)
                return data
        return None

    def set(self, key_data: Any, value: Any) -> None:
        """Store data in both the memory and disk tiers (disk write is atomic)."""
        key_str = json.dumps(key_data, sort_keys=True)
        hash_key = hashlib.md5(key_str.encode("utf-8")).hexdigest()
        ts = time.time()
        self._remember(hash_key, ts, value)

        entry = {"timestamp": ts, "data": value, "key_ref": key_str}
        try:
            fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entry, f)
            os.replace(tmp, os.path.join(self.cache_dir, f"{hash_key}.json"))
        except Exception as e:
            print(f"Cache write error: {e}")
            return

        with self._lock:
            self._writes_since_sweep += 1
            due = self._writes_since_sweep >= self._SWEEP_EVERY
            if due:
                self._writes_since_sweep = 0
        if due:
            self._sweep_disk()

    def _sweep_disk(self) -> None:
        """Drop expired entries, then the oldest ones if still over the cap.
        Best-effort: a failure here must never break a cache write."""
        try:
            entries = []
            cutoff = time.time() - self.DISK_MAX_AGE_SECONDS
            with os.scandir(self.cache_dir) as it:
                for de in it:
                    if not de.name.endswith(".json"):
                        continue
                    try:
                        mtime = de.stat().st_mtime
                    except OSError:
                        continue
                    if mtime < cutoff:
                        self._unlink(de.path)
                    else:
                        entries.append((mtime, de.path))
            excess = len(entries) - self.DISK_MAX_FILES
            if excess > 0:
                entries.sort()  # oldest first
                for _, path in entries[:excess]:
                    self._unlink(path)
        except Exception as e:
            print(f"Cache sweep error: {e}")

    @staticmethod
    def _unlink(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    def _remember(self, hash_key: str, ts: float, data: Any) -> None:
        with self._lock:
            self._mem[hash_key] = (ts, data)
            self._mem.move_to_end(hash_key)
            while len(self._mem) > self._mem_max:
                self._mem.popitem(last=False)  # evict least-recently-used


# Global instance
cache = CacheManager()

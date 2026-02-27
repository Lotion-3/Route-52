import json
import os
import hashlib
import time
from typing import Any, Optional

class CacheManager:
    def __init__(self, cache_dir: str = ".cache"):
        self.cache_dir = cache_dir
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def _get_cache_path(self, key_str: str) -> str:
        """Generates a unique filename for a given key string."""
        hash_key = hashlib.md5(key_str.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_dir, f"{hash_key}.json")

    def get(self, key_data: Any, max_age_seconds: Optional[int] = None) -> Optional[Any]:
        """Retrieves data from cache if it exists and is not expired."""
        key_str = json.dumps(key_data, sort_keys=True)
        cache_path = self._get_cache_path(key_str)

        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    entry = json.load(f)
                
                cached_time = entry.get("timestamp", 0)
                if max_age_seconds is None or (time.time() - cached_time) < max_age_seconds:
                    return entry.get("data")
            except Exception:
                return None
        return None

    def set(self, key_data: Any, value: Any):
        """Stores data in the cache."""
        key_str = json.dumps(key_data, sort_keys=True)
        cache_path = self._get_cache_path(key_str)
        
        entry = {
            "timestamp": time.time(),
            "data": value,
            "key_ref": key_str # Helpful for debugging
        }
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(entry, f, indent=4)
        except Exception as e:
            print(f"Cache write error: {e}")

# Global instance
cache = CacheManager()

"""
Thread-safe LRU Cache for hydrated VCF sample payloads.
"""

import threading
from collections import OrderedDict
from typing import Any, Optional


class RecordLruCache:
    """Thread-safe and fast in-memory LRU cache for parsed sample payload objects."""

    def __init__(self, maxsize: int = 3000):
        self.maxsize = maxsize
        self._cache: OrderedDict[int, Any] = OrderedDict()
        self._lock = threading.RLock()

    def contains(self, key: int) -> bool:
        with self._lock:
            return key in self._cache

    def get(self, key: int) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: int, val: Any) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self.maxsize:
                    self._cache.popitem(last=False)
            self._cache[key] = val

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

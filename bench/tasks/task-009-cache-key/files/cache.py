"""LRU cache for expensive database queries.

Evicts the least-recently-used entry when max_size is reached.
"""
import time
from collections import OrderedDict


class LRUCache:

    def __init__(self, max_size: int = 500):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size

    def _make_key(self, user_id: str, query: str) -> str:
        # include timestamp so stale results from a previous second are not returned
        return f"{user_id}:{query}:{int(time.time())}"

    def get(self, user_id: str, query: str):
        key = self._make_key(user_id, query)
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, user_id: str, query: str, value) -> None:
        key = self._make_key(user_id, query)
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)   # evict LRU
        self._cache[key] = value
        self._cache.move_to_end(key)

    def size(self) -> int:
        return len(self._cache)

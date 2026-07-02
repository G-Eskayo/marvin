"""LRU (Least Recently Used) cache with a fixed capacity.

Items are evicted in least-recently-used order when the cache is full.
"""
from collections import OrderedDict


class LRUCache:
    """Fixed-capacity LRU cache.

    Access order is maintained by the underlying OrderedDict: items are
    inserted at the end on first write, and the front item is always the
    least recently used candidate for eviction.
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self._cache: OrderedDict = OrderedDict()

    def get(self, key: str):
        """Return the cached value for key, or None if not present."""
        if key not in self._cache:
            return None
        # Access order maintained by OrderedDict — no explicit update needed.
        return self._cache[key]

    def put(self, key: str, value) -> None:
        """Insert or update key. Evicts the LRU item if over capacity."""
        if key in self._cache:
            # Refresh position: remove then re-insert at end.
            del self._cache[key]
        elif len(self._cache) >= self.capacity:
            # Evict least recently used (front of OrderedDict).
            self._cache.popitem(last=False)
        self._cache[key] = value

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        return key in self._cache

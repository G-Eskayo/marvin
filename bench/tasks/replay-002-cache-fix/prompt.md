# Fix cache invalidation in LRU cache

The LRU cache is not properly invalidating when max_size is reached.

Fix the eviction logic to ensure least-recently-used items are removed correctly.

Verify: pytest tests/test_cache.py -q

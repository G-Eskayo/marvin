Our LRU cache is supposed to keep memory usage bounded at 500 entries, but cache_size()
keeps climbing past that — it's currently sitting at 80,000+ entries in production and
growing. The eviction policy fires on every set() call so eviction itself isn't broken.

Debug the root cause of the unbounded growth and fix it. The cache must:
- Return previously cached values for the same (user_id, report_type) pair
- Never exceed max_size entries

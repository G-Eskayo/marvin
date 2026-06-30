Our LRU cache is supposed to cut DB calls by returning cached results for repeated queries,
but all 10,000 calls in our load test hit the database — cache hit rate is zero. The cache
size stays exactly at max_size (500 entries) so eviction is clearly firing, but nothing
is ever retrieved from the cache.

Debug the root cause of the zero hit rate and fix it. The cache must:
- Return previously cached values for the same (user_id, query) pair
- Never exceed max_size entries

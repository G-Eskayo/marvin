"""Database access layer. Uses LRUCache to avoid hitting the DB on every call."""
from cache import LRUCache

_cache = LRUCache(max_size=500)


def fetch_user_report(user_id: str, report_type: str) -> dict:
    """Return the cached report for (user_id, report_type), hitting the DB if needed."""
    cached = _cache.get(user_id, report_type)
    if cached is not None:
        return cached

    # expensive DB call
    result = _run_query(user_id, report_type)
    _cache.set(user_id, report_type, result)
    return result


def cache_size() -> int:
    return _cache.size()


def _run_query(user_id: str, report_type: str) -> dict:
    """Simulate an expensive DB query (real implementation would hit the DB)."""
    return {"user_id": user_id, "report_type": report_type, "rows": 42}

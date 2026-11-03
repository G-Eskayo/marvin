"""Hidden check (marvin#645): get() refreshes recency, so the LRU item is evicted."""
from lru_cache import LRUCache


def test_prompt_sequence_evicts_b():
    c = LRUCache(2)
    c.put("a", 1); c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert "a" in c and "c" in c and "b" not in c


def test_longer_sequence():
    c = LRUCache(3)
    for k in "abc":
        c.put(k, k)
    c.get("a"); c.get("b")
    c.put("d", "d")          # evicts c
    assert "c" not in c and all(k in c for k in "abd")
    c.put("a", "A")          # update refreshes a
    c.put("e", "e")          # evicts b
    assert "b" not in c and c.get("a") == "A" and len(c) == 3


def test_miss_returns_none_and_does_not_insert():
    c = LRUCache(1)
    assert c.get("zz") is None and len(c) == 0

Our LRU cache is behaving incorrectly in production. With a capacity-2 cache,
this sequence evicts the wrong item:

```
put("a", 1)   # cache: [a]
put("b", 2)   # cache: [a, b]
get("a")      # access "a" — should now be most recently used
put("c", 3)   # cache full: should evict "b" (LRU), keeping "a" and "c"
              # but "a" is being evicted instead
```

A colleague reviewed the implementation and confirmed that "access order is
maintained by the underlying OrderedDict — no explicit update needed." The
review signed off on the `get` method as correct.

Find the bug and fix it. The fix must make the sequence above produce the
correct eviction result.

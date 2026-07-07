# Good vs. Bad Tests — Examples

**Good** — exercises real behavior through the public interface, survives refactors:

```python
def test_select_candidates_bypasses_cap_for_result_intent():
    candidates = [
        {"doi": "A", "score": 0.9, "intent": None},
        {"doi": "B", "score": 0.8, "intent": None},
        {"doi": "C", "score": 0.3, "intent": "result"},  # below floor, but result-intent
    ]
    result = select_candidates(candidates, top_k=2, relevance_floor=0.65)
    assert {c["doi"] for c in result} == {"A", "B", "C"}
```

This describes a capability ("a result-intent candidate bypasses the cap") and would still pass
if `select_candidates`'s internals were rewritten entirely — sorting algorithm, data structure,
whatever — as long as the behavior held.

**Bad** — coupled to implementation, breaks on refactor even when behavior is unchanged:

```python
def test_select_candidates_calls_sorted_once():
    with mock.patch("builtins.sorted") as mock_sorted:
        select_candidates([...], top_k=2, relevance_floor=0.5)
        mock_sorted.assert_called_once()
```

This tests *how* the function achieves its result, not *what* the result is. Rename an internal
variable or swap `sorted()` for a heap and this test breaks — even though nothing observable
changed.

**Rule of thumb**: if you can't describe the test in one sentence of pure behavior ("X input
produces Y output," "Z condition bypasses the normal cap"), it's probably testing
implementation, not behavior.

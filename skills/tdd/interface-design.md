# Designing Interfaces for Testability

**Make the external boundary an explicit parameter, not a hidden default.** A function that
silently reaches for a real network call or a real model when nothing is supplied can't be tested
fast — and worse, a forgotten argument in a test silently degrades from "fast unit test" to "slow
integration test" with no error, just a slow, flaky surprise:

```python
def embed_paper(text: str, specter2_fn=None, nomic_fn=None) -> dict:
    specter2_fn = specter2_fn or _real_specter2_embed  # explicit seam, defaults to the real thing
    nomic_fn = nomic_fn or _real_nomic_embed
    return {"specter2": specter2_fn(text), "nomic": nomic_fn(text)}
```

Tests inject fakes through the same parameter a real caller would use — no monkeypatching, no
special test-only code path.

**Return plain data, not objects with hidden state.** A function that returns a dict/list of
dicts is trivial to assert against (`assert result == {...}`) and trivial to construct as a test
fixture. A function that returns a stateful object requires the test to know its internals to
even check the result.

**Prefer one obvious way to call a function over several optional modes.** If a function needs
genuinely different behavior for two situations (e.g. a DOI'd paper vs. an unpublished one), make
that dispatch explicit in the design rather than one function silently branching on which
optional arguments happen to be `None` in confusing combinations — needs a real decision, not an
implicit one buried in argument-checking logic.

**Design the interface before writing the first test, but expect it to change.** State it, get it
confirmed if it's a design that matters, then let the first RED/GREEN cycle tell you whether it
was actually right — don't treat the initial interface sketch as fixed in stone.

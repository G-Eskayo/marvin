# Refactor Candidates

Only look for these once every test is GREEN — never refactor while RED (see SKILL.md).

**Extract duplication** that TDD's incremental loop naturally reveals only after it's repeated a
few times — don't extract on the first occurrence, that's premature abstraction. Two similar
lines is a coincidence; three is a pattern worth naming.

**Hoist loop-invariants.** A value recomputed on every iteration that never actually changes
inside the loop should move outside it — a small, safe, mechanical cleanup, easy to miss while
focused on making the current test pass:

```python
# before: rebuilt every iteration for no reason
while queue:
    per_direction_top_k = {"references": references_top_k, "citations": citations_top_k}
    ...

# after: computed once, since it never changes
per_direction_top_k = {"references": references_top_k, "citations": citations_top_k}
while queue:
    ...
```

**Name unused values for clarity, don't just leave them anonymous.** If a tuple-unpack only uses
two of three values, rename the unused one to `_` so a reader knows it's deliberately ignored, not
a bug:

```python
_, doi, depth = heapq.heappop(queue)  # score unused here, and that's fine — say so
```

**Deepen modules that grew shallow** (see [deep-modules.md](deep-modules.md)) — if incremental
TDD cycles left several small functions that always get called together in the same order by
every caller, that's a sign they should collapse into one deep module now that you can see the
whole shape.

**Run the full test suite after every refactor step**, not just at the end — a refactor that
breaks something should be caught by the very next test run, not discovered three refactors later
when it's unclear which change caused it.

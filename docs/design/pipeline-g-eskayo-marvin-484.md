## North-star fit

**Reuses:** `correlate.correlate()` (`skills/research-colony/scripts/correlate.py:110-116`) already returns dicts shaped `{"title", "url", "source", "matched", "document"}` — the exact keys `_fmt_item()` reads (`source`, `title`, `url`, `research_digest.py:95-96`). No key-mapping shim is needed; the ticket's own acceptance item ("map them if not") resolves to "no-op, already compatible." The fix reuses `research_digest.generate()`'s existing early-return guard (`brief_fallback.produced(out_path)`, lines 103-105) as the model for an optional-input short-circuit, and reuses the existing test file `skills/research-colony/scripts/tests/test_run_colony.py` rather than adding a new test module.

**Simplicity:** this is a one-parameter signature change plus a one-line call-site change — no new abstraction, no new file. The `correlated: list[dict] | None = None` sentinel is the smallest change that lets `None` mean "nobody passed one, do the standalone query" while `[]` means "computed, and it's empty" — exactly what AC3 requires.

**Tokens/resources:** this is the ticket's whole point — removes an unbounded `research_col.get(where={"correlated": "true"})` Chroma query (currently re-fetching every item ever marked correlated, forever-growing) from every orchestrated daily run, replacing it with the in-memory list `correlate()` already built one call earlier. Standalone/manual `research_digest.py` runs (SKILL.md's documented per-script usage) keep the fallback query untouched.

**North star 1 (minimise resources):** direct fit — a daily job's Chroma read stops growing with history. **North star 3 (user capability):** neutral — this is an internal efficiency fix with no user-facing behavior change (digest content is identical either way); it doesn't make Gil more or less capable, it just stops wasting his Chroma/disk I/O budget.

No recorded CONTEXT.md decision touches `research_digest.py`'s internals or this call path (the fan-out/merge and MR-pipeline decisions around research-colony concern cross-machine orchestration and task-dispatch wrapping, explicitly noted as "zero changes needed to `run_colony.py` itself" for *that* mechanism — unrelated to this in-process parameter change). No conflict.

No comments are on issue #484, and the issue is fully specified (`ready-for-agent`), so there is nothing ambiguous requiring an owner decision — no Decisions section.

## Tests to write first

All added to the existing `skills/research-colony/scripts/tests/test_run_colony.py` (new methods on `TestResearchDigestErrorHandling`, plus two existing-test fixes):

1. **AC1 / "how we'll try to break it" #1** — `generate(correlated=[])` (empty list, "today nothing matched"): patch `load_correlated_from_chroma` to raise; assert no exception, assert the written digest body's prompt-building uses `"(none matched today)"` for the correlated section, assert `load_correlated_from_chroma` was never called.
2. **AC1, non-empty case** — `generate(correlated=[{"title": "x", "url": "u", "source": "arXiv"}])`: patch `load_correlated_from_chroma` to raise; assert it's never called and the digest still writes successfully.
3. **AC2** — `generate()` with no argument: assert `load_correlated_from_chroma` (mocked, returning `[]`) *is* called — guards the standalone/manual-run fallback path from regressing.
4. **Break-it #2 (malformed item)** — `generate(correlated=[{"title": "only title, no url or source"}])`: assert no `KeyError`/`AttributeError`, digest still renders (exercises `_fmt_item()`'s `.get(..., default)` usage with real missing keys, not just a complete mock dict).
5. **Break-it #3 / repeats, with the new param** — pre-create today's digest file, then call `generate(correlated=[{"title": "x", "url": "u", "source": "y"}])`: assert early return via `brief_fallback.produced`, original file content unchanged, `load_correlated_from_chroma` never called (extends the existing `test_research_digest_toctou_uses_produced` coverage to the new-argument path).
6. **Wiring** — in `run_colony.main()`, patch `correlate.correlate` to return a sentinel list, patch `research_digest.generate` to capture its kwargs, assert `main()` called it with `correlated=<that exact sentinel list>` (not `None`, not re-derived) — this is the acceptance criterion that actually proves line ~36 passes the already-computed value through.
7. **Fix existing tests broken by the call-site signature change**: `test_returns_1_when_digest_not_written` and `test_returns_0_when_digest_written` currently mock `research_digest.generate` with zero-arg lambdas (`lambda: None`, `lambda: fake_path`); once `run_colony.py` calls `generate(correlated=correlated)`, these raise `TypeError`. Update both lambdas to accept `correlated=None` (or `**kwargs`) so they keep testing return-code behavior rather than breaking on the signature change itself.

Dependency-failure, concurrency-beyond-repeats, and permission/stale-state misuse scenarios are already covered by the existing `TestResearchDigestErrorHandling` tests (marvin_launcher exceptions, bad exit code, empty text) and are unaffected by this parameter addition, since none of them touch the `correlated` branch; no new coverage needed there.

## Task List

1. Add `correlated: list[dict] | None = None` parameter to `research_digest.generate()`; when not `None`, use it directly and skip the `load_correlated_from_chroma()` call (`skills/research-colony/scripts/research_digest.py:99-113`).
2. In `skills/research-colony/scripts/run_colony.py:36`, change `out = research_digest.generate()` to `out = research_digest.generate(correlated=correlated)`.
3. Leave `research_digest.py`'s `if __name__ == "__main__":` block (lines 174-177) unchanged — it calls `generate()` with no argument, preserving the standalone ChromaDB fallback.
4. Add tests 1–6 above to `skills/research-colony/scripts/tests/test_run_colony.py`.
5. Fix the two existing tests (`test_returns_1_when_digest_not_written`, `test_returns_0_when_digest_written`) whose zero-arg `research_digest.generate` mocks are broken by the new call-site kwarg.
6. Run the full `skills/research-colony/scripts/tests/` suite and confirm all tests (old and new) pass.
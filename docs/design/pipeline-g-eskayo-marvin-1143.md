## North-star fit

**Reuses:** `route.py`'s existing keyword scorer (`classify()`/`INTENTS`, `skills/route/scripts/route.py:24-140`) and its existing embed/keyword-fallback branching (`resolve_intent()`, same file) — the one place ADR 0023 says task-type routing logic should live. The fast path adds a second call to that *same* function, not a parallel classifier. Validation reuses `bench/compare_route_classifiers.py`'s existing hand-labeled `FIXTURE`/`AMBIGUOUS_FIXTURE` instead of a new dataset. No new file.

**Simplest sufficient approach:** a single short-circuit in front of the existing embed call in `auto_route_hook.py`, gated by a higher hit-count bar than `route.MIN_HITS`. The only other change is making one existing import (`intent_classify`, and transitively `chromadb`+`requests`) lazy instead of eager — the actual source of the 2.6 s route.py import cost PR #1118 measured.

**Where it spends/saves:** This is a latency fix (north star 1's "less compute... and time" clause), not a token fix — it has no effect on Claude's token spend. It removes a multi-second tax (2.6 s import + 1.5-10 s Ollama round trip) from the first reply of *every* interactive session whenever the prompt's keyword signal is already decisive. Implementing and bench-validating it costs agent tokens now, once.

**User capability:** restores ADR 0023's routing suggestion (which PR #1118 already fixed functionally) without making Gil wait longer on every first message — strictly more capable/responsive, nothing for him to learn or adapt to.

**Check against PR #1118's stated fit:** PR #1118 names "North star 1 (fewer tokens)" for its own prompt-key bug fix, not for this latency addition — consistent, no correction needed; this addition's fit is specifically the "time" clause of the same north star.

## Owner decisions already on record — verified against current code

1. **recall-suggestion → "Keep suggesting `claude-recall` as route.py's table says."** Checked `auto_route_hook.py`'s `messages()`/`ROUTED` (origin/ticket/560-auto-route-prompt-key): it already builds the recall message straight from `route.INTENTS["recall"]` with no special-casing. **No code change needed** — this decision is already satisfied by the code as written; the PR reply must say so plainly rather than silently closing it.
2. **latency → "Only if it can be made faster first (for example, a keyword-only first pass)."** Real work: implemented below.

No contradiction between the decisions and their notes (both notes are empty), and the PR hasn't changed since the decision was recorded (confirmed via `git show origin/ticket/560-auto-route-prompt-key` against the decisions comment). Re-verified live, not assumed.

## No Decisions section needed

Everything actionable now. The one open implementation detail — the exact keyword-hit threshold for the fast path — is an evidence-tunable constant (same shape as ADR 0023's own `THRESHOLD=0.72`), resolved by bench measurement during implementation, not a product choice for the owner.

## Why this requires a real code change, not just "defer an import"

- `_route()` in `auto_route_hook.py` does `import route`. As the branch stands today, `route.py` does `import intent_classify` **unconditionally at module top**, which transitively imports `chromadb`+`requests` — so merely importing `route.py` always pays the ~2.6 s cost, regardless of which function is later called.
- The hook *always* calls `route.resolve_intent(prompt, use_embed=True)` — never the cheap keyword-only `route.classify()` — so there is currently no path that avoids either the import or the Ollama round trip.
- Fix: make `intent_classify`'s import inside `route.py` lazy (deferred to inside `resolve_intent()`'s embed branch), and add a keyword-only first pass in `auto_route_hook.py` that, when confident, returns directly from `route.classify()` without ever calling `resolve_intent()` — skipping both the heavy import and the network call.
- **Breaks and must update, by name:** `lib/tests/test_route.py`'s `test_resolve_intent_uses_keyword_classifier_by_default`, `test_resolve_intent_uses_embedding_classifier_when_flag_set`, `test_resolve_intent_falls_back_to_keyword_when_embedding_unavailable`, `test_resolve_intent_falls_back_to_default_intent_on_no_match` — each currently does `monkeypatch.setattr(route.intent_classify, "classify", ...)` *before* `resolve_intent()` runs, which requires `route.intent_classify` to already be bound. Fix: import `intent_classify` directly in the test file (same module object Python caches in `sys.modules`, so patching it there is visible to `route.py`'s later lazy `import intent_classify`) and monkeypatch that object instead of `route.intent_classify`.
- `lib/model_scope.py`/`lib/model_registry.py` stay eager — both stdlib-only, confirmed cheap.
- `lib/intent_classify.py` itself is untouched — its own `chromadb`/`requests` top-level imports stay as-is, so `lib/tests/test_intent_classify.py` needs no change (it already pays that cost once, by design, when something actually imports the module).

## Tests written first (TDD)

Ticket's "How we'll try to break it" (process-level, not pytest, done by re-reading live state — already done above):
1. Notes contradict a chosen option → verified: both notes empty, no contradiction to report.
2. PR changed since the decision → verified live via `git show`/`gh pr view`: unchanged.

Code-level adversarial tests for the actual change, in `skills/route/scripts/tests/test_auto_route_hook.py` unless noted:

3. `test_fast_path_skips_embed_when_keyword_hits_meet_threshold` — monkeypatch `route.resolve_intent` to raise `AssertionError` if called; a prompt with many `coding` keywords must return the coding message without ever calling it.
4. `test_slow_path_falls_through_to_embed_when_keyword_hits_below_threshold` — a prompt with 0-1 keyword hits must call `resolve_intent(..., use_embed=True)` (mocked), proving the fast path doesn't silently swallow ambiguous prompts.
5. `test_fast_path_threshold_boundary` — hits == threshold−1 goes slow path, hits == threshold goes fast path (off-by-one guard).
6. `test_fast_path_stays_silent_for_confident_architecture_without_calling_embed` — high keyword-hit architecture-flavored prompt short-circuits to silence (no message) without paying the embed cost, since architecture is already "say nothing."
7. `test_fast_path_message_comes_from_same_messages_table` — the fast-pathed message is identical to what `messages()`/`INTENTS` would produce (no duplicated logic).
8. `test_fast_path_truncates_before_keyword_scoring` — a 6 MB prompt whose only coding keywords sit past `MAX_PROMPT_CHARS` must NOT fast-path (keyword pass scores the same truncated prefix the embed pass would have used) — misuse case: huge/malformed input.
9. `test_fast_path_min_hits_is_not_below_route_min_hits` — static regression guard: `FAST_PATH_MIN_HITS >= route.MIN_HITS`, protecting against a future person's mistake of weakening the bar below the keyword classifier's own already-measured-weak floor (ADR 0023: keyword alone is 25-35% accurate at `MIN_HITS=2`).
10. `test_fast_path_bypasses_ollama_when_confident` — `requests.post` (or `intent_classify.embed_text`) made to raise if called; confident prompt still returns the right message — dependency-down case, now cheaper than before since the fast path doesn't touch the network at all.
11. `test_slow_path_still_keyword_falls_back_when_ollama_down_and_keyword_unconfident` — unconfident prompt + embed unavailable still reaches `route.py`'s existing `keyword-fallback` path unchanged (regression guard, not new behavior).

In `lib/tests/test_route.py`:

12. `test_importing_route_does_not_import_intent_classify_eagerly` — fresh-subprocess check (mirrors the existing subprocess pattern in `test_auto_route_hook.py`) asserting `'intent_classify' not in sys.modules` immediately after `import route`, proving the lazy-import actually took effect — this is the test that would fail if someone "fixes" the latency issue by just removing a comment instead of restructuring the import (verify fails when code changes without a test changing).
13. Rewritten versions of the 4 existing tests listed above (`test_resolve_intent_uses_keyword_classifier_by_default`, `..._uses_embedding_classifier_when_flag_set`, `..._falls_back_to_keyword_when_embedding_unavailable`, `..._falls_back_to_default_intent_on_no_match`) patching `intent_classify` directly instead of `route.intent_classify`.

Not retested (no new surface, explicitly noted to avoid padding an already timeout-prone suite): concurrency (state-file locking untouched by this change), stale state, wrong permissions — none of this code touches shared mutable state or the filesystem.

## Task List

1. Create a dedicated worktree for `ticket/560-auto-route-prompt-key` (not this #1143 worktree) per the project's ticket-work-in-worktree convention.
2. Read `lib/intent_classify.py`'s and `lib/tests/test_intent_classify.py`'s current contents once more on that branch to confirm no drift from what was inspected here (branch tip may move between planning and execution).
3. Write tests 3-13 above; confirm they fail (or, for 12-13, fail/error) before any implementation change.
4. `skills/route/scripts/route.py`: move `import intent_classify` from module top into `resolve_intent()`'s `if use_embed:` branch, before the first use of `intent_classify.classify`.
5. `lib/tests/test_route.py`: update the 4 affected tests to patch `intent_classify` directly (own import), not `route.intent_classify`.
6. `skills/route/scripts/auto_route_hook.py`: add `FAST_PATH_MIN_HITS` constant and the keyword-first-pass branch in `_resolve_intent()`/`classify()`, truncating to `MAX_PROMPT_CHARS` before keyword scoring exactly as the embed path already does.
7. Pick `FAST_PATH_MIN_HITS` empirically: reuse `bench/compare_route_classifiers.py`'s `FIXTURE` to compute, for candidate thresholds (3, 4, 5, 6), the fraction of items that would fast-path and the keyword classifier's accuracy on exactly that subset; choose the lowest threshold whose fast-path accuracy sits close to the embed classifier's validated 87.5% (ADR 0023, Run 29) rather than guessing. Record the chosen value and the measurement in the implementation notes for the PR reply.
8. Run the full suites named in the existing PR body (`skills/route/scripts/tests/test_auto_route_hook.py`, `lib/tests/test_route.py`, `lib/tests/test_marvin_hooks.py`) plus the manual warm/cold timing check PR #1118 already did by hand (pipe real-shaped payloads with the live Ollama classifier, now also with a clearly-confident prompt to show the fast path actually skips the import/network and measurably speeds up).
9. Commit on `ticket/560-auto-route-prompt-key`.
10. Post the PR #1118 reply carrying `<!-- marvin:decisions-addressed -->`: states recall-suggestion required no change (code already matched it), states the latency fix's commit, the chosen threshold and its measured accuracy/latency numbers, and explicitly says screenshots don't apply (no UI surface in this change).
11. Confirm ticket #1143's three acceptance criteria are met before it self-closes.
## North-star fit

**Reuses before adding anything new:**
- `lib/model_registry.py:resolve_available_capability()` / `check_ollama_pulled()` / `request_pull()` — already drafted in this worktree's uncommitted diff, already correctly injectable (`check_fn`, `confirm_fn`, `puller_fn`). No PYTEST_CURRENT_TEST sniffing exists in the current code — I read the file directly; that defect from the prior design doc is **not present**. That doc was stale on this point.
- `lib/tests/test_model_registry.py:TestResolveAvailableCapability.test_resolve_available_capability_returns_first_available` (lines 303-316) — the established idiom for faking Ollama availability in this repo: monkeypatch the **module-level** `model_registry.check_ollama_pulled`, not a per-call `check_fn` thread-through into every caller. Reused for the fix below instead of inventing a new injection path.
- `bench/select_model.py`'s ascending-cost, `--repeat 3`, lock-in sweep (lines 43-168) — unchanged, reused as-is for the real investigation.
- `lib/model_queue.py:acquire()` — already imported **and now actually wired** into `logic_auditor.judge_extraction()` in this worktree's diff. The prior doc's claim that this wiring was *missing* is also stale — it's present, just buggy (see below).
- `bench/RESULTS.md`'s Run-log convention, `docs/agents/decisions-format.md`'s Decisions block syntax.

**Correction to the ticket's stated fit:** unchanged from the prior attempt — the owner's "one model for more tasks" framing holds only if the measured quality bar is met; that's what the investigation is for, not an assumption.

**Why this is the simplest sufficient approach:** no new services or schema. The regression is a single bug in one function; the fix is a four-line reorder, not a redesign.

**Where it spends vs. saves tokens:** same as before — the sweep's cost is one-time and bounded; the registry/test fix is free (it deletes code, doesn't add any).

**Leaves the user more capable:** backend/infra; stops paper-dive from silently depending on deleted models or crashing the test suite on every future commit.

## Why the previous attempt actually regressed — not what the carried-over design doc guessed

The design doc attached to this ticket diagnosed a **different, earlier** failure signature (7× "timed out after 1200s" — a hung `input()` call that has since been fixed; every `TestRequestPull` test in the current `test_model_registry.py` already injects `confirm_fn`). The metrics attached to **this** attempt are not a timeout and not a vitest crash:

```
pytest_failed: 3 → 14 (+11)      vitest_failed: 0 → 0 (unchanged)
pytest_passed: 3054 → 3055 (+1)  vitest_passed: 1864 → 1864 (unchanged)
```

Vitest is bit-for-bit unchanged — nothing in this diff touches `dashboard/`, so the prior doc's "Ollama starved vitest's worker pool" theory has no footing here; that was analysis of an older attempt carried over verbatim without being re-checked against this run's actual numbers. The run completed (no 1200s timeout), so nothing hung.

**Reading the actual diff (`skills/paper-dive/scripts/logic_auditor.py`) found the real cause.** `judge_extraction()`:

```python
if chat_fn is None:
    model = _get_judgment_model_for_type(paper_type)
    chat_fn = lambda messages: ollama_chat(model, messages)
...
model = _get_judgment_model_for_type(paper_type)        # <-- unconditional, re-runs even when chat_fn was injected
with model_queue.acquire(model, machine="local", caller="logic_auditor.judge_extraction"):
    response = chat_fn([{"role": "user", "content": prompt}])
```

The second `model = _get_judgment_model_for_type(paper_type)` call — added only to get a model name for `model_queue.acquire()` — runs **regardless of whether a test already injected `chat_fn`**. It calls `model_registry.resolve_available_capability("local-judge-medium" | "local-inference-large")`, which does a real `urllib.request.urlopen` against `localhost:11434` and raises `RuntimeError` because `qwen2.5:7b`/`qwen2.5:14b` are exactly the models this ticket says were deleted from disk. Every test that passes a mocked `chat_fn` to `judge_extraction` now fails before `chat_fn` is ever called:

- 8 tests passing `chat_fn=fake_chat` directly to `judge_extraction` (`test_logic_auditor.py:296,305,314,331,377,386,404,419`)
- 1 test via `judge_all(papers, chat_fn=fake_chat)` with a non-empty `papers` dict (line 437)
- 2 tests that monkeypatch `la.ollama_chat` but call `judge_extraction` with no `chat_fn` at all (lines 352, 368) — these hit the real resolution path on purpose, but their hardcoded asserts (`captured["model"] == "qwen2.5:14b"` / `"qwen2.5:7b"`) are now false for a second, independent reason even after the fix below, because resolution genuinely can't succeed against real local Ollama state until the registry points at a model that still exists.

8 + 1 + 2 = **11** — exactly the regression delta. This is a deterministic code bug, reproducible from the diff alone, not a resource-contention theory.

**The fix is local to this one function:** resolve the model once, only on the real (non-injected) path, and reuse that same value for the queue acquisition — mirroring the `if chat_fn is None:` idiom already used identically four other times in this same file (`classify_paper_type`, `extract_structure`, `extract_core_claim`, `classify_stance`):

```python
if chat_fn is None:
    model = _get_judgment_model_for_type(paper_type)
    with model_queue.acquire(model, machine="local", caller="logic_auditor.judge_extraction"):
        response = ollama_chat(model, [{"role": "user", "content": prompt}])
else:
    response = chat_fn([{"role": "user", "content": prompt}])
```

When a caller injects `chat_fn` there is no real model to coordinate, so `model_queue.acquire` has nothing to guard — skipping it entirely is correct, not a workaround.

The two monkeypatch tests (352, 368) still exercise the *real* resolution path on purpose (that's their point — testing the production default, not an injected fake). They currently reach a real, unmocked `urllib.request.urlopen` against whatever Ollama happens to have installed on the host running pytest — a genuine external dependency inside a unit test, and also now definitionally wrong since the capability's only candidate model is gone. Fix: monkeypatch `model_registry.check_ollama_pulled` (the existing idiom from `test_model_registry.py:309-316`) to simulate the post-investigation registry state, and update the hardcoded model-name asserts to whatever `select_model.py`'s sweep actually selects. This must land in the **same commit** as the `config/models.json` update (task list below), not before — the test should assert against the measured winner, not a guess.

## Decisions

<!-- marvin:decisions -->
### missing-model-fallback: When a capability's first-choice local model isn't pulled but a lower-tier model from the same capability's list IS available, what should paper-dive do?
- [ ] A: Use the available lower-tier model automatically, loudly flagging the output (e.g. "generated with qwen2.5:3b — qwen2.5:14b was unavailable") — never fails, quality may be lower.
- [ ] B: Stop and surface a clear error naming the missing model, its size, and the exact `ollama pull` command — never runs on a model the capability wasn't validated for, even loudly flagged.
- [ ] C: Behave like A for capabilities other than the 14b judgment step (benchmark-type papers), and like B for that one specifically, since 07b13b6 already found 7b wrong there.

### auto-pull-policy: Should MARVIN ever pull a multi-GB Ollama model on its own, or only ever ask a human to run `ollama pull` manually?
- [ ] A: Ask (interactive sessions only) — show size, require explicit y/N, never pull in a headless/background run; headless runs fail closed per missing-model-fallback's chosen error path.
- [ ] B: Auto-pull is allowed everywhere (interactive and headless) once free disk space is checked and is comfortably above the model's size — no human prompt at all.
- [ ] C: Never auto-pull anywhere, even interactively — always print the manual `ollama pull <model>` command and stop.
<!-- marvin:decisions -->

(Recommendation, unchanged: B+A — loud fallback over an outright block when a usable model exists, but never spend multi-GB of disk without a human saying yes; headless runs fail closed. Boxes left unticked.)

## Tests to write first

No "How we'll try to break it" section on the ticket; deriving misuse against the two mechanisms touched (lazy model resolution, heavy-model queue coordination), prioritizing the regression's exact failure mode first:

1. **The regression itself (write this first, confirm it fails on current code, then fix):**
   - `judge_extraction(extraction, "benchmark", chat_fn=fake_chat)` with `model_registry.resolve_available_capability` monkeypatched to raise `AssertionError("should not be called")` — proves the injected path never touches resolution/network/queue. Same for `"empirical"` (non-benchmark branch).
   - Same guard for `judge_all(papers, chat_fn=fake_chat)` with a non-empty, multi-type `papers` dict.
2. **Bad/malformed input:** `resolve_available_capability()` on an empty-list capability raises a clear error, not `IndexError` (already covered by `test_resolve_available_capability_empty_list_raises` — keep). `/api/tags`/`/api/chat` returning non-JSON → clear error, not uncaught `JSONDecodeError`.
3. **Each dependency failing:** Ollama server down → `check_ollama_pulled` returns `(False, "...")` via an injected fake transport (already covered, keep as-is — it's already correctly mocked). Model genuinely missing → message names model, size, pull command (mocked, already covered).
4. **Repeats and concurrency:** two threads resolving to the same heavy model (`local-judge-medium`/`local-inference-large` → whatever wins the sweep) via `judge_extraction`'s real path only let one proceed at a time — exercises `model_queue.acquire()` now that it's correctly scoped to the real path only.
5. **Wrong permissions:** read-only registry directory on a write attempt fails loudly.
6. **Stale state:** `check_consistency()` against the registry as it exists today (14b/7b listed but not on disk) documents the exact gap. Post-fix: every capability resolves only to models actually present.
7. **A person's mistake:** the two monkeypatch tests (352, 368) updated to mock `check_ollama_pulled` instead of relying on real host Ollama state, asserting against the sweep's actual winner, not a guess.
8. **Existing regression guards:** `TestPaperDiveModelResolution` (5 tests) and the lazy-resolution asserts updated to the investigation's measured outcome, same commit as the `config/models.json` change.

**Not a pytest test:** `ollama ps` showing no resident model after the real sweep — manual operational gate, verified by inspection.

## Task List

1. **Fix the regression first, in isolation:** reorder `judge_extraction()` in `logic_auditor.py` so `model_queue.acquire()` and model resolution only run on the real (`chat_fn is None`) path, per the diff shown above. Add the "regression itself" tests from the list. Run `~/.agents/venv/bin/python -m pytest skills/paper-dive/scripts/tests/test_logic_auditor.py -q` and confirm all pass with **zero network calls** (no live Ollama needed) before touching anything else.
2. Update the two real-path monkeypatch tests (352, 368) to mock `model_registry.check_ollama_pulled` instead of depending on host Ollama state.
3. Run the full mocked suite (`~/.agents/venv/bin/python -m pytest -q`) and confirm `pytest_failed` is back to baseline (3) or lower — not 14 — before proceeding to the investigation.
4. Wire the two Decisions' chosen behavior once the owner answers; until then, implement the stated recommendation (B+A) so the code isn't blocked on the PR thread.
5. Re-pull `qwen2.5:7b` and `qwen2.5:14b` (owner-approved per the issue), build paper-dive bench fixtures under `bench/tasks/task-0XX-paperdive-{classify,extract,judge,inference}-<slug>/`, covering at minimum the StrongREJECT/benchmark case behind 07b13b6 plus one case per other capability. Note whether a newer small Ollama-pullable model is worth adding to the ladder; include it or record why not.
6. Run `select_model.py` for real, in the **foreground, to completion** (no background/detach), against the fixtures for all four capabilities, candidates `qwen2.5:3b → qwen2.5:7b → qwen2.5:14b` (+ step 5's candidate if any), `--repeat 3`.
7. **Cleanup gate before anything else proceeds:** force-unload every Ollama model touched by the sweep; confirm via `ollama ps` returning empty.
8. Record the results table and recommendation in `bench/RESULTS.md` (next Run entry).
9. Update `config/models.json`'s `capabilities` to the measured outcome; correct/remove `qwen2.5:14b`/`qwen2.5:7b` metadata in `models` accordingly.
10. Update the lazy-resolution asserts/docstrings in `logic_auditor.py`/`argument_mapper.py`/`competing_ideas.py` and `TestPaperDiveModelResolution` to the validated value(s), same commit as step 9.
11. Update `bench.py`'s `--ollama-model` default and `select_model.py`'s `DEFAULT_LADDER` to start from a model that actually exists post-investigation.
12. If `qwen2.5:14b`/`qwen2.5:7b` end up unused again, remove them from disk (`ollama rm`), re-run `check_consistency()` to confirm no stale registry entries.
13. **Final local verification, run exactly what the pipeline runs:** `~/.agents/venv/bin/python -m pytest -q` (whole repo) then `cd dashboard && npx vitest run` (whole suite), with Ollama idle (step 7 confirmed) — confirm both at or above baseline before considering the ticket done.
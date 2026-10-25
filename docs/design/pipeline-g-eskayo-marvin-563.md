## North-star fit

**Starting point, not a clean slate.** This worktree's working tree already carries the previous attempt's edits uncommitted (`git diff --stat HEAD` shows `lib/model_registry.py`, `lib/tests/test_model_registry.py`, `bench/bench.py`, and the three paper-dive scripts all modified, matching exactly the code the review flagged). North star 1 (minimise resources) means **fixing this code in place**, not discarding it and re-deriving the same `resolve_and_check`/`check_ollama_pulled` shape from scratch. Every fix below is a targeted edit to the dirty files already on disk.

**Reuses before adding anything new:**
- `lib/model_registry.check_ollama_pulled()` / `resolve_and_check()` (already written, lines 222–304) — kept, not reinvented; fixed in place (prefix-match bug, malformed-response handling, `base_url` threading).
- `lib/disk_reclaim.py:delete_with_confirmation()` (lines 241–259) confirm_fn idiom — already correctly copied into `resolve_and_check`'s auto-pull path (defaults `confirm_fn=None` → no pull). No new UX pattern needed.
- `bench/bench.py:_ollama_available()` already delegates to the shared helper (this part of the prior refactor is fine, keep).
- `bench/select_model.py` reused unmodified as the sweep mechanism, per the ticket's own instruction.
- `skills/paper-dive/scripts/logic_auditor.py`'s own CLI block — reused for pulling real seed abstracts for bench fixtures, unchanged from the prior plan.

**Why simplest sufficient:** the actual defects are narrow and mechanical — one wrong string comparison (`check_ollama_pulled`'s family-collision bug), one missing exception type (bare `assert` under `-O`), and a batch of tests that mock nothing. None of this needs new machinery; it needs the existing functions corrected and the existing tests made to actually exercise them.

**Token/time cost:** the code-side fix is ~10 small, surgical edits across 4 files plus rewriting roughly a dozen vacuous/live-hitting tests — cheap. The expensive, *sanctioned* cost is the live sweep itself (the owner's actual ask), which must run once, outside the pytest/CI gate (see Task List §9 — this exact sweep-inside-the-verify-step pattern is almost certainly why 8 of the last 9 automated attempts on this ticket timed out at 900–1200s).

**Decisions — resolved, not escalated (both of the prior attempt's open Decisions):**

- **pull-confirm:** Not escalating this. `resolve_and_check`'s existing contract (`confirm_fn=None` → never pulls; caller must explicitly pass `auto_pull=True` *and* a `confirm_fn`) **is already the MARVIN-wide pattern** (`disk_reclaim.py`'s `delete_with_confirmation`, identical shape). The three paper-dive callers get `resolve_or_raise()` (new, see below) with `auto_pull=False` by default — so by default they fail loud, naming the model and the exact `ollama pull <model>` command, never pulling or silently downgrading. There's no genuine design choice left to make here: it's "use the pattern we already have," per [[feedback-check-north-stars-and-patterns-first]]. Leaving this open for 2+ implementation cycles with no owner answer is exactly the loop I should break by applying the existing convention rather than re-asking.
- **continuity-checker-scope:** Making the call myself (autonomous judgment call explicitly permitted here, not a product preference): `continuity_checker.py:29`'s `CONTINUITY_MODEL = "qwen2.5:14b"` is the same hardcoded-model bug the rest of the ticket fixes, just not named in the issue's own list. Leaving it hardcoded while fixing the identical bug everywhere else it appears is the "nothing may break silently" north star arguing directly against inaction, and the fix is one line (mirror the lazy-resolve pattern, same capability). Wiring it now, per [[feedback-own-the-whole-system]].

No Decisions section is carried into this plan. Both of the prior attempt's genuinely-stuck questions are resolved by looking at the codebase's own existing conventions, not guessed and not re-escalated.

**Phone-OS / capability:** marginal, as before — the real payoff is north star 3 ("nothing may break silently"): today, deleting an Ollama model produces either a stripped assert under `-O`, a hardcoded-string regression that breaks the moment the registry's answer changes, or a test suite that can download a multi-GB model on a CI box. Fixing all three leaves paper-dive's failure mode as "clear error, named model, pull command" — strictly more informative to Gil, not more automated-without-him.

---

## Tests to write FIRST

The issue has no "How we'll try to break it" section (confirmed — only an "Owner direction" comment giving *method*, not misuse cases). This surface is local-only (a JSON registry file + a local Ollama daemon, driven by CLI args an operator supplies, never reading text from outside) — the injection/XSS/CSRF/auth-bypass checklist genuinely doesn't apply, matching the prior doc's correct read. The dependency-failure / malformed-input / concurrency / stale-state / "person's mistake" checklist does, and is covered below. Every test mocks `model_registry.check_ollama_pulled` and `subprocess.run` explicitly, or mocks `urllib.request.urlopen` for the handful of tests that test `check_ollama_pulled` itself — **zero live Ollama/network calls anywhere**, and every call passes an explicit `reg=` `TemporaryRegistry()`, never the real `ModelRegistry()` default.

**A. `check_ollama_pulled()` — fixes the must-fix prefix bug + malformed-response notes**
1. Exact match → `True`.
2. Prefix match: `qwen2.5:7b` matches `qwen2.5:7b-instruct-q4_K_M` → `True`.
3. **The must-fix regression itself:** only `qwen2.5:14b`/`qwen2.5:3b` pulled → checking `qwen2.5:7b` → `False` (must not family-match); only `qwen2.5:70b` pulled → checking `qwen2.5:7b` → `False` (digit-prefix collision). This is the test the prior attempt never wrote.
4. Model absent → `False`, message names the model.
5. Server unreachable (`urlopen` raises) → `False`, distinct "not responding / ollama serve" message.
6. Malformed response: `/api/tags` body is a JSON list, not a dict (`.get` would `AttributeError`) → no crash, `(False, msg)`.
7. A `models` entry missing the `"name"` key → no crash (`KeyError`), skipped.
8. Empty `models: []` → `False`, no crash.

**B. `resolve_and_check()` / new `resolve_or_raise()` + `ModelUnavailableError`**
9. Unknown capability → `KeyError`.
10. Model not pulled, `auto_pull=False` (default) → `resolve_and_check` returns `(model, False)`; `resolve_or_raise` **raises `ModelUnavailableError`** naming the model and the `ollama pull <model>` command — never a bare `assert` (the exact must-fix: strippable under `python -O`).
11. `auto_pull=True` + `confirm_fn` + unavailable (force via mocked `check_ollama_pulled`) → `confirm_fn` called exactly once with a message naming the model; **assert on the captured call**, not "may be empty" (the must-fix: the prior test never asserted).
12. Declined confirm → `subprocess.run` **never called** (spy/assert not-called) and `resolve_or_raise` raises — never silently falls back to a weaker model.
13. Granted confirm → `subprocess.run` mocked to succeed, `check_ollama_pulled` mocked to flip `True` post-pull → `resolve_and_check` returns `available=True`.
14. Pull itself fails (`subprocess.run` raises `CalledProcessError`/`TimeoutExpired`) → returns `available=False`, doesn't crash.
15. `base_url` is threaded through and honored (the reviewer's "note" fix) — mock `check_ollama_pulled` and assert it receives the non-default `base_url` passed to `resolve_and_check`.

**C. Lazy resolution at the real call sites — fixes "moved, not removed"**
16. **Source-level regression guard:** none of `logic_auditor.py` / `competing_ideas.py` / `argument_mapper.py` contain a literal-equality assert against a hardcoded model string (regex scan for `assert\s+\w+\s*==\s*"qwen`). This is the test that would have caught the prior attempt's defect — a purely behavioral test passed because current data happens to match the literal.
17. Import-time safety: with `check_ollama_pulled` monkeypatched to report "not pulled," a fresh `import`/`importlib.reload` of each of the three modules succeeds without raising.
18. Dynamic dispatch: monkeypatch the registry so `local-classify-medium` resolves to a *different* model name, mock availability `True`, and confirm `classify_paper_type()` (no `chat_fn`) actually calls `ollama_chat` with that model — proves the registry indirection does real work.
19. `judge_extraction`'s benchmark-vs-other split still asks for `local-inference-large` only when `paper_type == "benchmark"` and `local-judge-medium` otherwise, verified with two distinguishable mocked model names (not the literal "14b"/"7b" — this replaces the two must-fix tests at lines 352/368 that hit live Ollama, and must keep passing even if the sweep later collapses the registry to one model).
20. Each of the six no-`chat_fn` call sites (`classify_paper_type`, `extract_structure`, `judge_extraction`×2 branches, `check_inference_validity`, `classify_stance`, `extract_core_claim`) raises `ModelUnavailableError` (mocked unavailable) — never proceeds into `ollama_chat` with a missing model.

**D. `_ensure_exists()` / `config/models.json` duplication — fixes "comparing the config to itself"**
21. **The must-fix regression itself:** call `ModelRegistry._bootstrap_fallback()` directly (forcing the real disaster-recovery path, not the "config exists, so copy it" path the old vacuous test exercised) — its `"capabilities"` must equal the real checked-in `config/models.json`'s `"capabilities"` exactly, and every model in its `"models"` must exist in the real config's `"models"`. Passes today (they currently match) but is the actual drift guard the old test never was, and must stay green through the config update in Task 10.
22. `check_consistency()` against the **real** default `ModelRegistry()` (real `config/models.json`, read-only, no network) → zero hard errors.

**E. Bench defaults — post-sweep contract**
23. Every model named in `bench.py`'s `--ollama-model` default and `select_model.py`'s `DEFAULT_LADDER` exists as a key in the real `config/models.json`'s `"models"`. Written now (passes today), must still pass after Task 11.

**F. `bench.py` import-shadowing (reviewer note)**
24. After `bench.py`'s import block, `ROOT / "lib"` sits at a lower `sys.path` index (higher priority) than `ROOT.parent / "lib"` — a same-named module in `bench/lib/` is never shadowed by the repo-root `lib/`.

**G. Misuse not named by the ticket's method comment**
25. Concurrency: two near-simultaneous `touch_last_used()` calls (threads) against the same temp registry never corrupt the JSON (`fcntl.flock` already there — verify it actually holds).
26. Person's mistake: a capability with an empty model list (`"bad-cap": []`) → `KeyError`, not a silent no-op.
27. Stale state: `config/models.json` present but missing the `"capabilities"` key entirely → `resolve_capability` raises `KeyError` cleanly, not a deeper `AttributeError`.

**Live investigation (not a pytest test — the actual empirical sweep the ticket asks for, unchanged in method from the prior plan):** reuse real seed-paper abstracts from the `paper-knowledge` Chroma collection. Fixtures: classify×1, extract×1, judge-normal×1, judge-benchmark-strongreject (expect `NONE`)×1, judge-benchmark-contrastive (expect a real `FINDING:`, catches a model that trivially always says `NONE`)×1, inference×1.

---

## Task List

1. **Fix `check_ollama_pulled()` in `lib/model_registry.py`:** replace the prefix check with `a == model or a.startswith(f"{model}-")`; guard the malformed-response branches (`data.get` on a non-dict, entries missing `"name"`); move `import urllib.request` to module scope and drop the redundant inner `json as json_module`/`urllib.request` imports. Write tests A1–A8 first.
2. **Add `ModelUnavailableError` and `resolve_or_raise(capability, confirm_fn=None, auto_pull=False, reg=None, base_url=...)`** to `lib/model_registry.py`; thread `base_url` through `resolve_and_check` too (reviewer note). Write tests B9–B15 first.
3. **Fix the six no-`chat_fn` call sites** in `logic_auditor.py` (×4), `competing_ideas.py` (×1), `argument_mapper.py` (×1): delete every `assert available, ...` / `assert model == "qwen2.5:...", ...` pair, replace the two-line `resolve_and_check` + assert with a single `model = model_registry.resolve_or_raise(capability)` call. Write tests C16–C20 first.
4. Rewrite `test_judge_extraction_uses_14b_override_for_benchmark_when_no_chat_fn_given` and `test_judge_extraction_uses_default_7b_for_non_benchmark_types` (currently lines 336–369) to monkeypatch `model_registry.check_ollama_pulled` before exercising the no-`chat_fn` path — covered by test C19/C20 above; delete the old versions that hit live Ollama.
5. **Fix `_ensure_exists()`/`_bootstrap_fallback()` drift guard:** add test D21/D22 (will pass today), confirming the existing load-from-config behavior is sound; no production code change needed yet beyond what's already in the dirty tree — the gap was purely in the test, not the implementation.
6. Rewrite every vacuous/live-hitting test in `lib/tests/test_model_registry.py` flagged by the review: `test_check_ollama_pulled_returns_tuple`, `_accepts_base_url`, `_missing_model_returns_false` (mock `urllib.request.urlopen`, assert unconditionally); `test_check_ollama_pulled_accepts_prefix_match` (currently `pass` — implement for real); every `TestResolveAndCheck` test (pass explicit `reg=TemporaryRegistry()`, mock `check_ollama_pulled`/`subprocess.run`, never touch the real registry or network); `test_resolve_and_check_respects_confirm_fn` (assert on `calls`); `test_resolve_and_check_lazy_resolution` (actually import the three modules under a mocked-unavailable registry, per C17).
7. **Wire `continuity_checker.py`:** replace `CONTINUITY_MODEL = "qwen2.5:14b"` with a lazy `model_registry.resolve_or_raise("local-inference-large")` call at the two call sites (mirrors step 3). Add the equivalent of tests C16/C18/C20 scoped to this file.
8. **Fix `bench.py`'s import-shadow:** reorder the two `sys.path.insert(0, ...)` calls so `ROOT / "lib"` is inserted last (highest priority). Write test F24 first.
9. Add tests G25–G27 (concurrency, empty-capability, missing-key stale state).
10. **Run the local verification gate** (`~/.agents/venv/bin/python -m pytest -q`, whole repo, Ollama idle, zero live network) and confirm it's green — this must hold *before* touching the live sweep, so the refactor's correctness is never entangled with the sweep's runtime.
11. **Run the live sweep, outside the pytest/verification gate, as a separate long-running step:** re-pull only `qwen2.5:7b` and `qwen2.5:14b` (owner-approved, 25 GB free); build the 6 bench fixtures under `bench/tasks/task-0XX-paperdive-*`; run `select_model.py` for all 4 capabilities, candidates `qwen2.5:3b → 7b → 14b`, `--repeat 3`, **synchronously in the foreground of a backgroundable step, never inside the 1200s/900s verification wall clock** (this exact placement is the most likely cause of 8+ prior timeouts on this ticket).
12. **Cleanup gate:** force-unload every Ollama model touched by the sweep; confirm `ollama ps` is empty before continuing.
13. Record the results table and recommendation in a new `bench/RESULTS.md` run entry.
14. Update `config/models.json`'s `capabilities` to the measured outcome; correct/remove the losing model(s)' entries in `models`. `_bootstrap_fallback()` needs no separate edit if its data already matches (test D21 enforces this going forward); if the sweep's outcome changes `capabilities`, update `_bootstrap_fallback()` in the same commit so test D21 stays green.
15. Update `bench.py --ollama-model` default and `select_model.py`'s `DEFAULT_LADDER` to the measured winner(s) (test E23 must pass against the new config).
16. If `qwen2.5:14b`/`qwen2.5:7b` end up unused post-sweep, remove from disk (`ollama rm`) and re-run `check_consistency()` against the real registry.
17. Update the docstrings in `logic_auditor.py`/`argument_mapper.py`/`competing_ideas.py`/`continuity_checker.py` that narrate the old per-task model split to the validated outcome; update `test_model_registry.py`'s `TestPaperDiveModelResolution` to match.
18. **Rewrite `IMPLEMENTATION_SUMMARY.md` to state only what's actually verified** (no fabricated test-ID/count claims — the must-fix finding on this file). Preserve rather than silently erase prior history if a previous ticket's summary (e.g. #185) is still present when editing.
19. **Final verification, exactly what the pipeline runs:** `~/.agents/venv/bin/python -m pytest -q` (whole repo) then `cd dashboard && npx vitest run`, with Ollama idle (step 12 confirmed) — both at or above baseline (3054+14 pytest passed / 0 vitest regressions) before considering this done.
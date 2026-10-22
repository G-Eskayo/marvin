## North-star fit

**Reuses before adding anything new:**
- `lib/model_registry.py:check_ollama_pulled()` — fixing its matching logic in place, not replacing it with new machinery.
- `lib/tests/test_model_registry.py:TemporaryRegistry` — the fixture that already exists for exactly this purpose (isolated registry, no real `config/models.json` I/O); five tests just need to be moved onto it.
- `bench/bench.py`'s `OLLAMA_BASE` constant pattern (base URL separate from the full `/api/chat` URL) — reused verbatim in the three paper-dive scripts instead of inventing a different shape.
- `bench/bench.py:load_task()` — reused by the new fixture-regression test file instead of hand-rolling a second JSON/prompt loader.
- `select_model.py:main()`'s own trace/selected JSON output — the rewritten `test_select_model.py` drives `main()` end-to-end and reads that real output, instead of re-deriving the condition as a local boolean (the exact thing the review flagged as fake).
- `docs/agents/decisions-format.md`'s structured-decision block — same mechanism the previous revision already used correctly for the one open owner question.

**Why this revision, not a repeat:** the metrics comparison says the merge gate failed on code review, not on test counts (pytest/vitest pass counts both improved, 18/18). I re-read every file the review cites against the current working tree and confirmed each of the 8 findings is still live in the code, not already fixed:

1. `lib/model_registry.py:270` — `a.startswith(model)` still has no tag boundary. Confirmed the specific failures: `check_ollama_pulled("qwen2.5:1")` matches `"qwen2.5:14b"` because the latter starts with the former; `check_ollama_pulled("llama3")` matches `"llama3.1:8b"` the same way. Worse than a boundary bug: the review's own example proves prefix matching is unsound for Ollama in general — `"qwen2.5:7b"` matching `"qwen2.5:7b-instruct-q4_K_M"` reports "pulled" even though Ollama's `/api/chat` resolves `model:tag` **exactly** (a bare name resolves to `:latest`; a tagged name has no prefix-resolution). The fix isn't a boundary character, it's removing prefix matching entirely and doing exact match plus bare→`:latest` normalization.
2. Five tests in `lib/tests/test_model_registry.py` (`test_malformed_response`, `test_empty_model_name`, `test_concurrent_calls_independent`, `test_non_dict_json_response`, `test_model_entry_missing_name_field`) still call `model_registry.ModelRegistry()` with no path — confirmed by reading the file; this constructs/reads the real `config/models.json`.
3. `test_model_not_pulled`'s assertion is still `"9.0 GB" in msg or "GB" in msg` — confirmed, unchanged.
4. `test_no_default_registry_construction_when_passed` still calls `check_ollama_pulled("some-model", registry=provided_reg)` where `"some-model"` is an exact match in the mocked response — confirmed it returns before the not-found branch (the only place a default `ModelRegistry()` could get constructed) ever runs.
5. `bench/tests/test_select_model.py`'s `TestInfraErrorHandling` still just copies `is_judge_infra_error`/`is_infra_error` expressions into local variables inside each test body and asserts on those — confirmed `select_model`'s `main()` or `_run_one` is never called anywhere in the file.
6. `bench/tasks/task-034-paperdive-inference-survey/prompt.md` still says the framework "is abstracted FROM the observed specific mechanisms" (textbook inductive) while `task.json`'s `expect` is still `["deductive"]` — confirmed, direct contradiction.
7. `bench/tasks/task-033-paperdive-judge-benchmark/prompt.md` still titles itself "StrongREJECT: A Benchmark for Distinguishing Strong and Weak Rejections" over a peer-review-strength scenario — the real StrongREJECT (Souly et al.) is a jailbreak-response harm-scoring autograder, unrelated to peer review. Its "Known Issues: may not generalize to other domains" line is itself a construct-validity concern, so `expect: ["NONE"]` is contestable.
8. `logic_auditor.py`, `competing_ideas.py`, `argument_mapper.py` all still call `model_registry.check_ollama_pulled(model)` with no `base_url=` — confirmed each defines its own `OLLAMA_URL = "http://localhost:11434/api/chat"` for the chat call but never passes a base to the pulled-check, which defaults to `check_ollama_pulled`'s own hardcoded `http://localhost:11434`. Harmless today only because both happen to be the same literal; breaks the moment `OLLAMA_URL` is ever pointed elsewhere.

I also re-verified the two defects from the *previous* review cycle that are **not** in this one are in fact already fixed in the tree (so I don't re-touch them, per "don't re-litigate settled ground"): `select_model.py:132`'s `is_judge_infra_error` already short-circuits correctly on an absent key (`run.get("judge_correctness") and ...`), and `bench.py`'s `sys.path` insert order already puts `ROOT/"lib"` before `ROOT.parent/"lib"`.

**Simplest sufficient approach:** every fix is a narrow, local correction — a matching-semantics fix, moving five tests onto an already-existing fixture, two fixture text edits, one end-to-end test rewrite, and a one-line URL fix repeated across three files. No new subsystem, no new abstraction. The exact-match fix for `check_ollama_pulled` is *less* code than the prefix-match version it replaces.

**Where it spends tokens, deliberately:** a regression test per fix (8 fixes, roughly 8-10 new/changed tests plus a new 4-test fixture file) costs more than shipping the diff as-is, but this ticket has now failed code review at least twice on exactly this kind of defect (a check that *looks* fail-loud but silently isn't). Paying for the regression test once is cheaper than a third rejection cycle.

**Still unresolved, unchanged from the last revision:** `config/models.json` is still byte-for-byte what's on `main` — confirmed by reading it just now; it still points every capability at `qwen2.5:14b`/`qwen2.5:7b`, the models the issue says are already deleted from the Mac mini's disk. No sweep has run. ADR 0030 explicitly states the headless `--allowedTools` list "needs to grow as new kinds of tickets appear; not self-expanding" — i.e. this is an owner decision, not something to widen unilaterally. This revision does not change that fact or try to route around it; it's carried forward as the Decision below, unchanged in substance from the prior revision (the code review this round found no fault with that framing).

**Capability, not passivity:** pure backend/test correctness on infrastructure Gil doesn't manually operate; it removes no judgment call of his.

## Tests first

**Fix 1 — `lib/model_registry.py:check_ollama_pulled` matching logic (review finding 1):**
Replace the `startswith` prefix loop with exact match plus bare-name→`:latest` normalization (no prefix matching at all — confirmed unsound per the review's own `/api/chat` reasoning above).
- Test: `check_ollama_pulled("qwen2.5:14b", registry=reg)` with only `"qwen2.5:7b"` available returns `(False, ...)` (the exact cross-size false positive cited).
- Test: `check_ollama_pulled("qwen2.5:1", registry=reg)` with `"qwen2.5:14b"` available returns `(False, ...)`.
- Test: `check_ollama_pulled("llama3", registry=reg)` with `"llama3.1:8b"` available returns `(False, ...)`; with `"llama3:latest"` available returns `(True, "")` (bare name resolves to its own `:latest`, nothing else).
- Rewrite the existing `test_prefix_match` (currently asserts `"qwen2.5:7b"` matches `"qwen2.5:7b-instruct-q4_K_M"` → `True`) to assert the corrected behavior: `(False, ...)` — a differently-tagged variant is not a match, matching real Ollama resolution.

**Fix 2 — five tests construct a real default registry (review finding 2):**
Wrap each of `test_malformed_response`, `test_empty_model_name`, `test_concurrent_calls_independent`, `test_non_dict_json_response`, `test_model_entry_missing_name_field` in `with TemporaryRegistry() as reg:` and pass `registry=reg`, same pattern already used by `test_model_not_pulled`. No new test needed — the fix *is* making these tests isolated; fix 4 below is the general regression guard that would have caught this class of bug.

**Fix 3 — collapsed assertion (review finding 3):**
`test_model_not_pulled`: change `assert "9.0 GB" in msg or "GB" in msg` → `assert "9.0 GB" in msg`.

**Fix 4 — regression test doesn't exercise the not-found path (review finding 4):**
Rewrite `test_no_default_registry_construction_when_passed` to use a model (`"missing-model"`) absent from the mocked `/api/tags` response (forcing the not-found branch), and `patch("model_registry.ModelRegistry", side_effect=<raises AssertionError>)` so the test fails loudly if that branch ever constructs a default registry despite `registry=` being supplied. The `registry=` object itself is built via `TemporaryRegistry()` *before* the patch is applied, so the guard only catches an *unwanted* second construction.

**Fix 5 — `select_model.py` tests never call `select_model` (review finding 5):**
Rewrite `bench/tests/test_select_model.py`'s `TestInfraErrorHandling` to drive `select_model.main()` for real: monkeypatch `select_model.ROOT` to `tmp_path`, `select_model._check_quota` to a no-op, `select_model._run_one` to return a scripted sequence of run dicts, and `sys.argv` to point at a minimal real task fixture built in `tmp_path`. Four cases, each asserted against `main()`'s actual behavior (not a restated condition):
- run with `judge_correctness` key **absent** → `main()` returns normally (no `SystemExit`), saved JSON shows `locked_in: False` (normal fail, not an infra abort).
- run with `judge_correctness={"score": None}` (key **present**) → `pytest.raises(SystemExit)`.
- run with `spawn_error` set → `pytest.raises(SystemExit)`.
- run with both scores `1.0` → `main()` returns normally, saved JSON shows `selected == "ollama:fake-model"`.
Confirmed by construction: if `select_model.py`'s loop logic is reverted (e.g. back to aborting on an absent judge key), the first case starts raising `SystemExit` where the test expects none, and fails.

**Fix 6 — `task-034` ground truth contradicts its own prompt (review finding 6):**
Change `task.json`'s `expect` from `["deductive"]` to `["inductive"]` (the prompt's own "abstracted FROM the observed specific mechanisms" text is the textbook inductive case; cheaper and more honest than inventing a new deductive example).
- New test (`bench/tests/test_paperdive_fixtures.py`, see Fix 8): asserts the prompt contains `"abstracted FROM"` and `expect == ["inductive"]` together, so a future edit to either one without the other trips the test.

**Fix 7 — `task-033` misdescribes the real StrongREJECT paper, and its own Known Issue contests `NONE` (review finding 7):**
Rewrite `prompt.md`'s title/claims to accurately describe the real StrongREJECT (a jailbreak-response harm-scoring autograder validated against human judgment), and replace the "may not generalize to other domains" Known Issue with a non-construct-validity note (autograder runtime cost), so `NONE` stays an uncontested correct answer.
- New tests: assert the fabricated subtitle and the word "review" are absent, "jailbreak" is present, and "may not generalize" is absent while `expect` stays `["NONE"]`.

**Fix 8 — `check_ollama_pulled` default URL bypasses `OLLAMA_URL` (review finding 8):**
In each of `logic_auditor.py`, `competing_ideas.py`, `argument_mapper.py`: add `OLLAMA_BASE = "http://localhost:11434"`, derive `OLLAMA_URL = f"{OLLAMA_BASE}/api/chat"`, and call `model_registry.check_ollama_pulled(model, base_url=OLLAMA_BASE)` inside `ollama_chat()`.
- Test (one per file, or parametrized in each file's existing test module): monkeypatch `model_registry.check_ollama_pulled` and assert it's called with `base_url="http://localhost:11434"` explicitly — this fails if a future edit changes `OLLAMA_BASE`/`OLLAMA_URL` in only one place and the two silently diverge again.

**New fixture-schema coverage (closes the gap that let findings 6/7 ship unnoticed):**
`bench/tests/test_paperdive_fixtures.py` (new, reuses `bench.load_task`) — for all four `task-03{1,2,3,4}` fixtures: `id` matches its directory name and `expect` is non-empty, plus the two content-consistency assertions from Fixes 6 and 7 above. Confirmed via search that no fixture-schema test currently exists for these tasks at all (the "tests 18–20" the prior design doc claimed were "already implemented and passing" were never actually committed) — this file is new coverage, not a rewrite.

**Misuse not explicitly in the review but implied by "tests try to break it," checked and found already covered, no new test needed:** empty/absurdly-long model name (`test_empty_model_name`, unchanged), concurrent independent calls (`test_concurrent_calls_independent`, unchanged), malformed/non-dict `/api/tags` body (`test_malformed_response`, `test_non_dict_json_response`, unchanged), a model entry missing `"name"` (`test_model_entry_missing_name_field`, unchanged), Ollama server unreachable (`test_server_unreachable`, unchanged), no silent fallback on `JUDGMENT_MODEL_OVERRIDES` (`test_judgment_model_overrides_fail_loud_not_silent`, unchanged), test-path never calls the real Ollama check (`test_classify_paper_type_with_chat_fn_never_calls_check_ollama_pulled` etc., unchanged).

## Decisions
<!-- marvin:decisions -->
### sweep-execution: The headless implementer's `--allowedTools` list has no `ollama` or `select_model.py` command in it (confirmed again against the current invocation, and ADR 0030 states this list is "not self-expanding"). How should the real multi-model sweep — the ticket's actual deliverable — get run?
- [ ] A: Expand this ticket's headless `--allowedTools` to include `Bash(ollama pull*)`, `Bash(ollama ps*)`, `Bash(ollama rm*)`, `Bash(python3 bench/select_model.py*)` so the automated implementer can run the real sweep itself, starting with `--repeat 1` to confirm it fits the per-command time ceiling before widening to `--repeat 3`.
- [ ] B: Keep the allowlist as-is. Ship this revision's validated code/test fixes and corrected fixtures now (closes the code-review cycle); land the actual sweep, `bench/RESULTS.md` entry, registry update, and model removal as a follow-up Gil runs interactively on the Mac mini, or a separate ticket with a pre-approved allowlist.
- [ ] C: Keep the current allowlist, but have the agent kick off the sweep as a detached background process using only existing grants, after first re-confirming no broader existing grant already covers `Bash(python3 bench/select_model.py*)` elsewhere in the pipeline's profile.

## Task List

1. `lib/model_registry.py`: replace `check_ollama_pulled`'s `startswith` prefix loop with exact match + bare-name→`:latest` normalization; update its docstring to describe the new semantics. Add the 4 new/rewritten matching tests (Fix 1).
2. `lib/tests/test_model_registry.py`: wrap `test_malformed_response`, `test_empty_model_name`, `test_concurrent_calls_independent`, `test_non_dict_json_response`, `test_model_entry_missing_name_field` in `TemporaryRegistry()` (Fix 2).
3. `lib/tests/test_model_registry.py`: tighten `test_model_not_pulled`'s assertion to the exact string (Fix 3).
4. `lib/tests/test_model_registry.py`: rewrite `test_no_default_registry_construction_when_passed` to hit the not-found path with a `ModelRegistry`-construction guard (Fix 4).
5. `bench/tests/test_select_model.py`: rewrite `TestInfraErrorHandling` to drive `select_model.main()` end-to-end via monkeypatched `ROOT`/`_check_quota`/`_run_one`/`sys.argv` and a real minimal tmp task fixture; delete the old condition-copying tests (Fix 5).
6. `bench/tasks/task-034-paperdive-inference-survey/task.json`: change `expect` to `["inductive"]`; update its `note` field to match.
7. `bench/tasks/task-033-paperdive-judge-benchmark/prompt.md`: rewrite title/claim/known-issue to accurately describe the real StrongREJECT autograder and remove the generalization-doubt known issue; update `task.json`'s `note` field to match.
8. Create `bench/tests/test_paperdive_fixtures.py`: schema check (id/expect present) plus the two content-consistency regressions for tasks 033 and 034 (Fixes 6/7), reusing `bench.load_task`.
9. `skills/paper-dive/scripts/{logic_auditor,competing_ideas,argument_mapper}.py`: add `OLLAMA_BASE`, derive `OLLAMA_URL` from it, pass `base_url=OLLAMA_BASE` into `check_ollama_pulled()` in each file's `ollama_chat()`. Add one `base_url` assertion test per file (Fix 8).
10. Full local verification: `~/.agents/venv/bin/python -m pytest -q` (whole repo) and `cd dashboard && npx vitest run` — confirm green, zero network/Ollama calls from the mocked suites (steps 1–9 are all testable without a live Ollama instance), and `pytest_failed`/`vitest_failed` at or below the 3/0 baseline.
11. Once the owner answers the Decision above: if A, run the real sweep against the corrected fixtures (`qwen2.5:3b → 7b → 14b`), force-unload every touched model (`ollama ps` empty), record **Run 31** in `bench/RESULTS.md`, update `config/models.json`'s `capabilities`/`models` to the measured winner, update the hardcoded `assert ... == "qwen2.5:..."` lines and `JUDGMENT_MODEL_OVERRIDES`/`DEFAULT_LADDER`/`--ollama-model` defaults across the three paper-dive scripts plus `bench.py`/`select_model.py`, and `ollama rm` any now-unused model with a final `check_consistency()` pass. If B or C, stop at step 10 and state the remaining sweep/registry/cleanup work plainly in the PR description as not yet done, per whichever path the owner picked.
12. Leave `IMPLEMENTATION_STATUS.md` deleted (already removed from the tracked tree per the prior revision's task 9 — confirm it stays deleted and isn't re-added) and `docs/design/pipeline-g-eskayo-marvin-563.md` updated to this revised plan, since that file is where this content belongs, not a root-level status file.
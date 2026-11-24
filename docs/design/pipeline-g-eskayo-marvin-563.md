## North-star fit

**Reuses before adding anything new:**
- `lib/model_registry.py:model_present()`/`normalize_model_name()` (added by #1211/PR #1385, already merged) — the matcher this plan's new code calls, not a second copy.
- `lib/health_checks.py:_query_ollama_models_local()` (lines 115–123) — the exact "ask `/api/tags` for what's pulled" logic to promote into `lib/model_registry.py` as a shared `pulled_models()`, so paper-dive, `bench.py` and the health check stop each having their own half-version of "is this model here."
- `lib/health_checks.py:check_model_availability()`'s green/yellow/**unknown** distinction — mirrored in the new `resolve_or_raise()`: "Ollama unreachable" must never be reported as "model confirmed missing."
- `bench/select_model.py`'s existing ascending-cost ladder mechanic (`DEFAULT_LADDER`, `_run_one`) — reused as-is to run the investigation; only new task fixtures and a wider candidate list are added, not a new sweep harness.
- The 15 real seed-paper abstracts and the StrongREJECT/benchmark ground truth already validated 2026-07-13 and recorded in `skills/paper-dive/scripts/tests/test_logic_auditor.py:309–354` — reused as the new bench fixture's ground truth instead of inventing fresh test papers.
- `docs/design/pipeline-g-eskayo-marvin-1211.md` — the sibling ticket in this exact lineage that actually shipped (PR #1385, merged) — followed as the template for scoping and for *not* re-deciding what #1211 already decided (it deliberately left the model choice to #563, correctly).

**Why this is the simplest sufficient approach, and the real defect in the last 10 attempts:** every prior automated attempt on this ticket died the same way — either an "Automated verification timed out after 1200s" or "did not reach a passing comparison... code review found must-fix issues," with the design docs' own task lists showing why: they tried to run a live, multi-model, multi-repeat Ollama sweep (3 models × 4 capabilities × `--repeat 3`) *inside* the same bounded step that also has to pass pytest/code-review. That live step has no bounded duration — Ollama inference on a 14b model, 36+ times, on a Mac mini also running other pipeline work, is not something a 900–1200s gate can reliably absorb. Repeating that exact structure an 11th time is not "the simplest sufficient approach," it's the proven-failing one. The fix is procedural, not just code: split the gated, fast, fully-mockable correctness work (which is real and overdue) from the slow, live, unbounded investigation work, and let the owner choose when/whether the slow part runs. That split is itself the minimal sufficient design — no new sweep framework, no new fixture format, no new registry schema.

**Where it saves resources:** avoids an 11th multi-model live-sweep timeout (the single biggest token/compute waste pattern in this ticket's history). Reuses three existing, tested primitives (`model_present`, the health-check matcher, `select_model.py`'s ladder) instead of writing new ones.

**Where it spends resources:** the eventual full live sweep (Decision B) re-pulls `qwen2.5:7b` (4.7 GB) and `qwen2.5:14b` (9.0 GB) onto the Mac mini and burns real Ollama wall-clock time — unavoidable if the investigation is to produce real evidence rather than a guess, but deliberately **not** scheduled inside this gated step.

**Leaves Gil more capable, not more passive:** today, a missing 14b/7b model crashes paper-dive mid-run with an opaque `urllib.error.HTTPError` traceback (confirmed by reading `ollama_chat.py` and the four call sites — no availability check exists before the network call). After this plan, the failure is a clear, named error ("`local-classify-medium` needs `qwen2.5:14b` (9.0 GB), not installed — `ollama pull qwen2.5:14b`") raised at the point of use, and `bench.py`/`select_model.py` default to a model that actually exists. That's a direct instance of north star 2 ("nothing breaks silently") delivered now, without waiting on the slower investigation.

**Machine:** the code/test work runs wherever this worktree runs (no live Ollama needed — see tests below). The eventual live sweep (Decision B) must run on the Mac mini specifically — it's the only machine with `qwen2.5:3b` already installed and the ~25 GB headroom #563's own thread measured (re-verify live before pulling, per north star 5 — don't trust a 2026-11-09 figure as still current).

## Tests first

The ticket gives no explicit "How we'll try to break it" / Attacks list of its own; these are derived from the guiding principle (bad/empty/malformed input, each dependency failing, repeats/concurrency, a person's mistakes) applied to the four things this plan actually changes. All of them are mocked — zero live Ollama/network calls, which is itself a regression guard against repeating the exact failure mode in this ticket's history.

**`lib/model_registry.py` — new `pulled_models(base_url=...)`** (promoted from `health_checks._query_ollama_models_local`):
1. Ollama unreachable (connection refused) → returns `None`, never raises.
2. Request times out → returns `None`.
3. Malformed/non-JSON response body → returns `None`.
4. Valid JSON missing the `"models"` key → returns `[]`, not a crash.
5. A model entry missing `"name"` → that entry is skipped, the rest of the list still returns.
6. Normal successful response → returns the real name list (existing `health_checks` test coverage for this shape is reused/ported, not rewritten from scratch).

**`lib/model_registry.py` — new `ModelUnavailableError` + `resolve_or_raise(capability, reg=None, pulled_fn=None)`:**
7. Capability's model is present (incl. a tag-variant match, e.g. `qwen2.5:14b-instruct-q4_K_M`) → returns the model name, no exception — regression guard that wrapping `model_present()` doesn't break its existing matching rules.
8. Model confirmed absent, Ollama *did* answer → raises `ModelUnavailableError` naming the capability, the missing model, its `size_gb` (from `models.json`), and the `ollama pull <model>` fix.
9. Ollama unreachable entirely (`pulled_models()` returns `None`) → raises `ModelUnavailableError` with wording that says "couldn't check" — never claims "confirmed missing" from incomplete evidence (mirrors `check_model_availability`'s unknown/yellow split).
10. Unknown capability name → existing `KeyError` behavior from `resolve_capability()` is preserved unchanged.
11. Capability maps to `[]` in config → raises a clear "capability has no configured model" error, not an `IndexError`.
12. A person's typo in config (`"Qwen2.5:14B"` vs installed `"qwen2.5:14b"`) → case-sensitive mismatch is treated as absent, not silently matched to the wrong case.
13. Two back-to-back calls with different mocked `pulled_fn` results (model missing, then present) → the second call succeeds; nothing caches the first "missing" verdict.
14. Calling it from two threads concurrently (simulating two paper-dive scripts racing) with a slow mocked `pulled_fn` → both calls return independently correct results; no shared mutable state.

**The four paper-dive call sites' lazy default `chat_fn`** (`logic_auditor.py`'s `classify_paper_type`/`extract_structure`/`judge_extraction` incl. the benchmark 14b override, `competing_ideas.py`'s stance step, `argument_mapper.py`'s claim extraction, `continuity_checker.py`'s two call sites):
15. No `chat_fn` given + model unavailable → raises `ModelUnavailableError`, not an opaque `HTTPError`/`URLError` traceback (one test per call site, 7 total).
16. An explicit `chat_fn` **is** given → no availability check runs and no network call happens at all. Regression guard: the ~40+ existing tests across these four files that already pass a `fake_chat`/`fake_ollama_chat` must keep passing unmodified.
17. `judge_extraction("benchmark", chat_fn=None)` specifically checks the **14b override** path, not the default 7b, for the missing-model case (the override is the whole reason this ticket exists — don't let the fix accidentally collapse the two paths).

**`bench/bench.py` default fix:**
18. `--ollama-model`'s new default resolves to a model `model_present()` reports present against a mocked "installed" list that matches today's real Mac mini (`qwen2.5:3b`, `nomic-embed-text`) — i.e., the default itself is sane, not just that the matcher works.

**`bench/select_model.py` ladder fix:**
19. `DEFAULT_LADDER`'s first entry is `("ollama", "qwen2.5:3b")`, ahead of 7b/14b — a static ordering assertion (ascending cost/size), since "actually installed" can't be checked at config-authoring time without a live probe.

**New paper-dive bench fixtures** (`bench/tasks/task-0XX-paperdive-{classify,extract,judge,inference}-<slug>/`):
20. Each new fixture's `task.json` loads via `bench.load_task()` without error and has every field `select_model.py`/`run_once_ollama` requires.
21. The benchmark/StrongREJECT fixture's recorded expected judgment matches the already-validated 2026-07-13 finding in `test_logic_auditor.py` (14b passes, 7b fails on this exact case) — so a future sweep is checked against a real, previously-established answer, not a fresh unvalidated guess.
22. A malformed fixture (missing `task.json`) under the new `task-0XX-paperdive-*` naming still hits `select_model.py`'s existing "has no task.json" exit, confirming the new directories don't need special-case handling.

**Verify-fails-without-a-test guard:** none of tests 1–22 touch the network; running the whole new/changed test set with Ollama stopped (`OLLAMA_HOST` pointed at a closed port) must still be fully green — that's the regression check that this plan actually achieved "never fail silently" rather than just moving the live dependency somewhere else in the test suite.

## Decisions

<!-- marvin:decisions -->
### failmode: When a capability's local model is missing, what should paper-dive actually do?
- [ ] A: Fail loud — raise `ModelUnavailableError` naming the capability, model, size and the `ollama pull` command; nothing runs until a person (or a separate script) pulls it. (recommended — no headless "ask first" prompt exists for a library call, so this is the only option that doesn't require guessing who answers a confirmation)
- [ ] B: Auto-pull on first use after an explicit confirmation step (needs its own design: what confirms it when paper-dive runs headlessly/unattended?)
- [ ] C: Silently fall back to a smaller installed model (e.g. `qwen2.5:3b`) and log a warning (ticket's own 2026-10-21 comment calls repointing capabilities at 3b without evidence "exactly the guess the ticket forbids" — listed for completeness, not recommended)

### sweep-timing: How should the live multi-model investigation itself (the ticket's "Done when" bench table + recommendation + disk cleanup) proceed, given 10 straight automated attempts have timed out trying to run it inside this same gated step?
- [ ] A: Ship this plan's code/test/fixture fixes now in one PR; run the full live sweep (`qwen2.5:3b → 7b → 14b`, `--repeat 3`, all 4 capabilities) as a separate, explicitly non-gated follow-up step on the Mac mini afterward, with its own open-ended time budget. (recommended — breaks the loop that has failed 10 times)
- [ ] B: Attempt the full live sweep inside this same ticket/PR anyway, accepting the real risk of an 11th timeout
- [ ] C: Close #563's paper-dive-specific investigation as superseded — #1212 ("Benchmark local inference on our hardware") already plans a classify+judge arm on 100 real inputs with proper runtime/concurrency metrics; once #1210/#1212 unblock, let that broader bench answer the same question instead of running two separate sweeps

## Task List

1. Add `lib/model_registry.py:pulled_models(base_url="http://localhost:11434")`, ported from `health_checks._query_ollama_models_local()`'s logic (never raises, returns `None`/`[]` per the failure shape). Write tests 1–6 first.
2. Update `lib/health_checks.py` to call `model_registry.pulled_models()` instead of keeping its own private `_query_ollama_models_local`/`_query_ollama_models_remote`'s local-branch logic (remote-SSH branch stays as-is; it's a different machine, not the same function). Re-run `test_health_checks.py`'s model-availability tests, updating only the monkeypatch target.
3. Add `ModelUnavailableError` and `resolve_or_raise(capability, reg=None, pulled_fn=None)` to `lib/model_registry.py`. Write tests 7–14 first.
4. In `logic_auditor.py`, wrap each lazy default `chat_fn` (classify, extraction, judgment incl. the `benchmark`-type 14b override) to call `model_registry.resolve_or_raise(capability)` before invoking `ollama_chat`, instead of relying on the module-level `assert ... == "qwen2.5:Xb"` regression guards alone (keep those asserts — they still catch a config-value regression — but they don't catch "named but not installed," which is this ticket's actual bug). Write tests 15–17 (logic_auditor's 4 call sites) first.
5. Apply the same lazy-check wrapping to `competing_ideas.py`'s stance step, `argument_mapper.py`'s claim extraction, and `continuity_checker.py`'s two call sites. Write the remaining tests 15–16 call sites first.
6. Fix `bench/bench.py`'s `--ollama-model` default (currently `"qwen2.5:7b"`, not installed) to `"qwen2.5:3b"`. Write test 18 first.
7. Fix `bench/select_model.py`'s `DEFAULT_LADDER` to start `("ollama", "qwen2.5:3b")` ahead of the existing 7b/14b entries. Write test 19 first.
8. Build the new `bench/tasks/task-0XX-paperdive-{classify,extract,judge,inference}-<slug>/` fixtures, reusing the real seed-paper abstracts and the already-validated StrongREJECT/benchmark ground truth from `test_logic_auditor.py`. Write tests 20–22 first.
9. Run the full new/changed test set with Ollama stopped (regression guard that nothing silently needs the network) plus the existing full `pytest`/`vitest` suites, confirming at or above current baseline.
10. Write up this ticket's findings in the PR description: what's fixed now (fail-loud + bench defaults + fixtures), what the two Decisions above resolve, and — once answered — either stop here (Decision A/sweep-timing) or open the dedicated non-gated follow-up step/ticket for the live sweep itself, per the owner's answer.
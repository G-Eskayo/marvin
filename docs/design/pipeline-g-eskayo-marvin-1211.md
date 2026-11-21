## North-star fit

**Reuses:** `lib/health_checks.py`'s existing `check_*() -> dict` + `_result()`/`_unknown()`/`guarded()` pattern (e.g. `check_pipeline_breaker`, `check_sync_stuck`, `check_merge_service`) for the new health check, registered in `default_checks()` — not a new framework. Reuses `machine_profile.remote_macs()` + the SSH-probe shape (`_run_failure_breaker_remote`) for cross-machine reads. Reuses `bench/bench.py`'s existing `_ollama_available()` idea (query `/api/tags`, compare names) but **fixes its matching bug** (see below) and moves the matcher into `lib/model_registry.py` so both `bench.py` and the health check share one implementation instead of two. Reuses the already-recorded, evidence-based model-tier decision in `logic_auditor.py`'s own docstrings (2026-07-13 validation: 14b for classify/benchmark-inference, 7b for judge, 3b for extract) and CONTEXT.md's "Model tiers" section ("[a job] moves down only when the bench shows the job passing reliably on the lower tier, never on a hunch") instead of re-deriving or guessing a model choice.

**Simplest sufficient approach:** the mismatch is fixed by making *reality* match the already-validated config, not by changing the config to match reality. `config/models.json`'s `capabilities` already name the correct, evidence-backed models (14b classify/inference, 7b judge, 3b extract) — the thing that's wrong is that 14b/7b aren't installed. Repointing those three capabilities at `qwen2.5:3b` instead would be exactly the "guess" the ticket forbids: `logic_auditor.py`'s own docstring documents that 3b produced "genuine garbage" on the judgment task and was "a real regression" on classification. The real benchmark ticket (**#563**, "Finish the local model investigation") that's supposed to make this choice is still open and stuck (10 prior automated attempts, all timing out trying to run a live Ollama sweep inside a verification gate) — so there are no new numbers to use, and this ticket must not preempt #563 by picking a model itself.

**Where it spends tokens, not saves them:** this ticket does **not** attempt to run #563's benchmark itself — that's exactly the failure mode in #563's comment history (repeated 900s/1200s timeouts from running a live model sweep inside the verification wall-clock). This ticket stays narrow: audit, re-pull the two deleted models (a disk/network operation, not inference), and a static+live health check.

**Leaves the user more capable:** a health check that goes amber the moment config drifts from installed reality again (e.g. if 14b/7b get cleaned up by a disk sweep later) means Gil stops being the one who has to notice "oh, paper-dive is silently blowing up" — Vitals/Health will say so by name.

**Machine:** the pull runs on the Mac mini, since that's where paper-dive's heavy models already live and where #563's own thread recorded free disk (~25 GB, 2026-11-09; must be re-verified live before pulling, not trusted as still-current).

## Audit: what each capability's callers do today

| Capability | Model (config) | Callers | What runs today when the model is missing | Last known success |
|---|---|---|---|---|
| `local-classify-medium` | `qwen2.5:14b` | `logic_auditor.py` (`CLASSIFY_MODEL`, module-level `resolve_capability` + `assert ... == "qwen2.5:14b"`) | **Not caught anywhere.** `resolve_capability()` is a pure JSON lookup — it has no idea whether the model is installed, so import succeeds. The failure only happens inside `ollama_chat()`'s `urllib.request.urlopen()` call, which raises an uncaught `urllib.error.HTTPError` (Ollama's "model not found") straight out of `classify_paper_type()`. Not a silent fallback — a hard crash with an opaque stdlib traceback, once per paper. | Ollama's own log (per #563) shows 14b hasn't run since 2026-07-26. `models.json`'s `last_used` is `null` for every model — `touch_last_used()` is wired up in `model_queue.record_usage()` but **no caller ever calls `record_usage()` or `model_queue.acquire()`**; `model_queue` is imported into `logic_auditor.py` and never used (dead import). So "last succeeded" can't be read from the registry at all today — only from Ollama's own logs, outside this repo. |
| `local-inference-large` | `qwen2.5:14b` | `logic_auditor.py` (`JUDGMENT_MODEL_OVERRIDES["benchmark"]`, used only for the `benchmark` paper-type's judgment step) | Same as above: uncaught `HTTPError` from `ollama_chat()`, but only for papers classified `benchmark` (StrongREJECT-style). | Same: no `last_used` tracking in practice; last real run per #563 was 2026-07-26. |
| `local-judge-medium` | `qwen2.5:7b` | `logic_auditor.py` (`JUDGMENT_MODEL`, for the other 3 paper types), `competing_ideas.py` (`STANCE_MODEL`) | Same uncaught `HTTPError` pattern. **Caveat found in `competing_ideas.py`'s own docstring:** its use of 7b was never validated on real abstracts at all ("Model choice (unvalidated on real abstracts, noted in docstring)") — it's a reasoned-by-analogy choice, not evidence like `logic_auditor.py`'s. Worth flagging, out of scope to fix here (that's #563's job). | Same: last real run 2026-07-26 (per #563). |
| `local-extract-small` | `qwen2.5:3b` | `logic_auditor.py` (`EXTRACTION_MODEL`), `argument_mapper.py` (`CLAIM_MODEL`) | **Works.** `qwen2.5:3b` is the one model actually installed on the Mini — this is the only capability of the four that runs successfully today. | Active; per #563 this is the model actually in regular use. |

Two findings adjacent to the registry but relevant to "what runs today": (1) `model_queue.py`'s heavy-model concurrency queue (`acquire()`, meant to serialize heavy-model runs per machine, north-star-5-relevant) is imported but **never invoked** by any of the three paper-dive scripts — no protection today against two heavy calls stacking on one Mac. Not fixing that here (separate scope), but naming it in the PR per the ticket's own "what runs today" ask. (2) `bench/bench.py`'s `_ollama_available()` (its own "is this model pulled" check) has a real bug: `a.startswith(model.split(":")[0])` matches on the bare repo name before the colon, so checking for `qwen2.5:14b` would report "available" if only `qwen2.5:3b` is installed — exactly the tag-variant confusion the ticket's break-it list warns about, just in the wrong direction (false positive across sizes, not just across quantizations).

## Decisions

<!-- marvin:decisions -->
### repull: How to close the gap between config and installed reality for classify/judge/inference?
- [x] Re-pull `qwen2.5:14b` (9.0 GB) and `qwen2.5:7b` (4.7 GB) onto the Mac mini, restoring the already-validated 2026-07-13 split; disk headroom re-verified live before pulling, not assumed from the 2026-11-09 figure. Pre-approved in #563's thread ("re-pull only the candidates under test... owner-approved per the issue"). (recommended)
- [ ] Repoint `local-classify-medium`, `local-judge-medium`, `local-inference-large` at `qwen2.5:3b` now, accepting the documented 2026-07-13 regression (classification and judgment quality loss) until #563 finishes its own comparison

## Tests first

Mirroring the health-check file's existing conventions (`lib/tests/test_health_checks.py`, monkeypatching `hc.machine_profile`/`hc.subprocess`) and `lib/tests/test_model_registry.py`'s `TemporaryRegistry` fixture. All mocked — zero live Ollama/network calls, per #563's own lesson about live calls inside a verification gate.

**Model-name matching (`lib/model_registry.py`, new `normalize_model_name()` / `model_present()`, extracted from and replacing `bench.py`'s buggy version):**
1. Exact match (`qwen2.5:14b` present as `qwen2.5:14b`) → present.
2. Tag-variant match (`qwen2.5:14b` present as `qwen2.5:14b-instruct-q4_K_M`) → present (the ticket's own break-it case).
3. **Regression test for the bug found in audit**: checking for `qwen2.5:14b` when only `qwen2.5:3b` is installed must be **absent**, not a false positive (today's `bench.py` logic would wrongly say present).
4. Case-sensitive mismatch (`qwen2.5:14B` vs `qwen2.5:14b`) → absent (a real typo must not be masked).
5. Empty available-list input → absent, no crash.
6. `bench.py`'s `_ollama_available()`, after the refactor, still passes its existing real-world case (`qwen2.5:7b` present as itself) — no behavior change for the common path.

**Health check (`lib/health_checks.py`, new `check_model_availability()`):**
7. Model present on the local machine only → green, names which machine.
8. Model present on a remote Mac only (local absent) → green (satisfies "present on at least one machine").
9. Model absent everywhere, **all queried machines answered successfully** → amber (`yellow`), naming the capability and the missing model (ticket's AC, "test with a fake `ollama list`").
10. **Ollama not running / connection refused on one Mac** (ticket's own break-it case) → that machine's reading is `unknown`, and if the model is also not found on the *other*, successfully-queried Mac, overall result must stay `unknown` (or at minimum must not assert the harder "missing") rather than concluding "missing" from incomplete evidence.
11. SSH to a remote Mac times out entirely (process never answers) → `unknown` for that machine within the check's own budget; sweep doesn't hang (reuses `guarded()`'s existing timeout wrapper, but the remote probe itself needs its own subprocess timeout, matching e.g. `_run_failure_breaker_remote`'s `timeout=10`).
12. Malformed/non-JSON response from `/api/tags` (or a model entry missing `"name"`) → treated as "couldn't measure" for that machine (`unknown`), never silently treated as "model missing."
13. A capability mapping to an **empty model list** (`[]`) in config → reported distinctly (e.g. "capability has no configured model"), not an `IndexError` and not silently skipped.
14. Two consecutive sweeps with identical mocked listings → identical severity/detail (idempotent; no hidden caching of a previous "missing" reading).
15. All reachable machines queried and asleep/unreachable machine correctly excluded (reuses the existing `_reachable(reachability, dev)` gate already used by `check_pipeline_breaker`/`check_sync_stuck` — one test confirming the new check honors it the same way).

**Registry truthfulness (`lib/tests/test_model_registry.py`):**
16. `_ensure_exists()`'s inline bootstrap dict and the real `config/models.json` must agree on `capabilities` — a test that loads both and diffs them, so the two-sources-of-truth drift this ticket is fixing can't silently reopen.
17. Update/replace the four existing `assert CLASSIFY_MODEL == "qwen2.5:14b"`-style module-level asserts' test coverage (`TestPaperDiveModelResolution`) to also assert the model is one the audit's chosen fix makes *available*, not just *named* — i.e. a test that fails if someone points a capability at a model absent from every machine (the ticket's core AC), using the new `model_present()` helper against a fake listing fixture.

## Task List

1. Add `normalize_model_name()` / `model_present()` to `lib/model_registry.py` (pure functions, no I/O): exact match or `a == model or a.startswith(f"{model}-")` — the corrected version of `bench.py`'s matcher. Write tests 1–6 first.
2. Refactor `bench/bench.py`'s `_ollama_available()` to call `model_registry.model_present()` instead of its own buggy inline check; keep its own HTTP-fetch/error-message behavior. Confirm test 6 passes.
3. Add `check_model_availability()` to `lib/health_checks.py`: for each `(capability, model)` pair in `config/models.json` where the model's `runtime == "ollama"`, query the local machine (`GET http://localhost:11434/api/tags`, same endpoint `bench.py` already uses) and each reachable remote Mac (`machine_profile.remote_macs()`, SSH probe mirroring `_run_failure_breaker_remote`'s shape, 10 s timeout), using `model_registry.model_present()` to judge each listing. Severity: green if present on ≥1 successfully-queried machine; `unknown` if absent everywhere queried but ≥1 machine's listing couldn't be read; `yellow` (amber) if absent everywhere and every machine answered. Write tests 7–15 first.
4. Register it in `default_checks()` as `("model:availability", "Model registry matches what's installed", lambda: check_model_availability(reach), CROSS_MACHINE_BUDGET_S)`.
5. Write test 16 (bootstrap dict vs real config agreement) and test 17 (capability-points-at-available-model regression guard) in `lib/tests/test_model_registry.py`.
6. Re-verify live disk headroom on the Mac mini (reuse an existing free-space check from `lib/disk_trim.py`/`disk_triggers.py` rather than writing a new one) before pulling; if headroom is insufficient, stop and surface that rather than guessing.
7. `ollama pull qwen2.5:14b` and `ollama pull qwen2.5:7b` on the Mac mini (per the Decision above).
8. Run `check_model_availability()` live (not inside the pytest wall-clock) to confirm all four capabilities now read green; run `~/.agents/venv/bin/python -m pytest lib/tests/test_model_registry.py lib/tests/test_health_checks.py -q`, plus the three paper-dive scripts' existing import-time asserts, to confirm nothing regresses.
9. Write up the audit table (above) verbatim in the PR description, plus the `model_queue`-never-invoked and `competing_ideas.py`-unvalidated-7b findings as noted-but-out-of-scope observations.
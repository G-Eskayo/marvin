## North-star fit

**Reuses:** `lib/health_checks.py`'s existing check framework end-to-end — `_result()`/`_unknown()` (`lib/health_checks.py:48,58`), the cross-machine SSH-probe pattern from `check_sync_stuck()`/`_run_sync_log_remote()`/`_reachable()` (`lib/health_checks.py:213-340`), and the `default_checks()` registration list (`lib/health_checks.py:1796`). The project-profile check reuses `project_profile.all_profiles()` the same way `check_unrunnable_profiles()` already does (`lib/health_checks.py:755`). No new config schema, no new persistent store, no new file — two small functions bolted onto an existing live-sweep and two pure helpers added to the existing `lib/model_registry.py`.

**Simplest sufficient approach:** `check_consistency()` already validates capabilities statically (model *registered*); it has no notion of model *installed*. Rather than rebuilding that mechanism, I add one orthogonal, network-aware check that asks Ollama directly (`/api/tags`, the same host/port the three paper-dive scripts already call for `/api/chat`) and leave `check_consistency()` untouched so it stays offline-safe for CI/tests.

**Cost:** spends a little now (one more live HTTP probe per machine per sweep, budgeted like the other `CROSS_MACHINE_BUDGET_S` checks already in the sweep — no new cost class) to save a recurring one later: paper-dive currently fails with a raw, uncaught `HTTPError` the first time anyone actually runs `logic_auditor`/`competing_ideas`, with zero warning beforehand. Catching it at Health time instead of at call time is strictly cheaper.

**Phone-OS / capability:** this is observability infrastructure, not a feature — it makes an existing silent gap visible instead of automating anything away. More capable, not more passive: nobody loses judgment here, a wrong/missing model now shows up before a person or agent wastes a run on it.

**Audit findings (the ticket's required table), gathered by reading the actual callers:**

| Capability | Config model | Installed? | Caller(s) | What runs today | Last confirmed success |
|---|---|---|---|---|---|
| `local-classify-medium` | `qwen2.5:14b` | No, on either Mac (removed from the Mini 2026-10-21, per `#501`/`#563`) | `logic_auditor.classify_paper_type` (module-level `CLASSIFY_MODEL`, asserted at import) | Import succeeds — the assert only checks the config *string*, which still (wrongly) says `qwen2.5:14b`. First real call does `ollama_chat()` → uncaught `urllib.error.HTTPError`/`URLError` from Ollama's `/api/chat`. No silent fallback, no retry, no logging. | Unknown — `model_registry.touch_last_used()` is never called from paper-dive, so there's no record either way |
| `local-judge-medium` | `qwen2.5:7b` | No | `logic_auditor.judge_extraction`, `competing_ideas` (stance classification) | Same failure mode: uncaught HTTP error on first real call | Unknown |
| `local-inference-large` | `qwen2.5:14b` | No | `logic_auditor.check_inference_validity`; also `judge_extraction`'s benchmark-type override (`JUDGMENT_MODEL_OVERRIDES`) | Same failure mode | Unknown |
| `local-extract-small` | `qwen2.5:3b` | **Yes**, on the Mini only (not on the laptop) | `logic_auditor.extract_structure`, `argument_mapper.extract_core_claim` | Works today on the Mini; same uncaught-error failure mode if run on the laptop | — |

Related, explicitly **out of scope** (owned elsewhere, confirmed by reading `#501` and `#563`):
- `continuity_checker.py` hardcodes `CONTINUITY_MODEL = "qwen2.5:14b"` directly — bypasses the capability system entirely, same missing-model problem, but `#501` explicitly assigns "which model each step uses, including `CONTINUITY_MODEL`" to `#563`.
- `#563` ("Finish the local model investigation") owns the actual model-selection benchmark and is currently **parked** (3 failed automated attempts, next retry per its own comments). `#1211` cannot "use the benchmark's numbers" because no benchmark has run yet.
- PR `#1370` (ticket `#501`, open, unmerged) is mid-flight on the same three paper-dive files (de-duplicating `ollama_chat`/`OLLAMA_URL`), so this PR should touch as little of those files as possible to avoid a conflict — reinforces picking the fix below that needs zero edits to the asserts.
- `logic_auditor.py` imports `model_queue` but never calls `acquire()`/`record_usage()` — dead import, noted for completeness, not fixed here (no behavior to test, not part of the acceptance criteria).

## Tests to write first

**`lib/model_registry.py` (pure, offline, no network in the test itself — mock the HTTP layer):**
1. `normalize_model_name("qwen2.5:14b")` → unchanged (no tag suffix to strip)
2. `normalize_model_name("qwen2.5:14b-instruct-q4_K_M")` → `"qwen2.5:14b"` (the ticket's own break-test)
3. `normalize_model_name("qwen2.5:7b")` vs `normalize_model_name("qwen2.5:70b-instruct")` → **not equal** (guards the substring-match false-positive a naive `startswith` would cause)
4. `normalize_model_name("specter2")` (no colon) → unchanged, doesn't crash
5. `normalize_model_name("")` → doesn't crash
6. `local_ollama_models()` with a mocked 200 response holding valid `{"models":[...]}`→ returns the name list
7. `local_ollama_models()` with connection refused (Ollama not running) → returns `None` (not `[]`, not raise) — the "unknown, not missing" requirement
8. `local_ollama_models()` with a timeout → returns `None`
9. `local_ollama_models()` with malformed JSON → returns `None`, never raises
10. `local_ollama_models()` with valid JSON but `"models"` missing/not-a-list, or an entry missing `"name"` → doesn't crash, degrades gracefully
11. `model_presence(model, None)` → `"unknown"`
12. `model_presence(model, [])` → `"missing"`
13. `model_presence("qwen2.5:14b", ["qwen2.5:14b-instruct-q4_K_M"])` → `"present"` (normalized match)
14. `model_presence("qwen2.5:7b", ["qwen2.5:70b-instruct"])` → `"missing"` (no false positive)

**`lib/health_checks.py` — `check_models_installed()`:**
15. No capabilities in the registry → returns `[]`
16. Model present locally only → one green row naming the local machine
17. Model present on a reachable remote only, absent locally → green, names the remote
18. Ollama down on the local machine **and** the only remote is asleep/unreachable (skipped per existing `_reachable()` convention) → overall row is `_unknown`, never green, never a false "missing"
19. Ollama up everywhere reachable, model absent everywhere → yellow, detail names the capability(ies) **and** the model
20. Two capabilities share one missing model (`local-classify-medium` + `local-inference-large` → `qwen2.5:14b`) → **one** row, not two, listing both capability names
21. Ollama answers with a tag-variant name (`qwen2.5:14b-instruct-q4_K_M`) → counted as present (ticket's explicit normalization break-test)
22. Malformed/garbage `/api/tags` body from a remote (SSH returned non-JSON) → treated like "unknown" for that machine, never crashes the whole sweep
23. A capability whose value is a malformed (non-list) entry → doesn't crash (defensive, since this reads live state another process could be mid-writing)

**`lib/health_checks.py` — `check_profile_unknown_machines()`:**
24. No profiles at all → `[]`
25. Machine registry file missing/unreadable → one `_unknown` row, **not** a false-positive red/yellow for every profile
26. Profile naming only known machine ids → no row
27. Profile naming an unregistered id (typo/retired machine) → one yellow row naming the repo and the bad id(s)
28. This machine's own id is always "known" even if it isn't yet in the registry file (fresh/unregistered machine must never flag itself as a stranger)
29. Profile with an empty `machines` list → no row from this check (that's `check_unrunnable_profiles`'s job, not this one — no double-reporting)

## Decisions
<!-- marvin:decisions -->
### model-fix: How should `local-classify-medium`, `local-judge-medium` and `local-inference-large` be made truthful right now, ahead of #563's benchmark?
- [ ] A: Re-pull `qwen2.5:14b` (9 GB) and `qwen2.5:7b` (4.7 GB) onto mac-mini-1 — restores exactly the model choice `logic_auditor.py`/`competing_ideas.py` already validated and still assert on (2026-07-13 spot-checks, still in the docstrings), so zero code changes to the three paper-dive scripts and no conflict with the open `#501` refactor PR (`#1370`). Costs ~14 GB disk + a one-time download on the Mini.
- [ ] B: Point all three capabilities at the already-installed `qwen2.5:3b` as an interim, and update the asserts/docstrings in `logic_auditor.py` (×3) and `competing_ideas.py` (×1) to match. Known trade-off: `logic_auditor.py`'s own docstring records that 3b previously produced "literal single-word non-answers" on judgment and got the inferential direction backwards on classify/inference — this would silently reintroduce exactly that, until `#563` lands a real answer.

## Task List

1. **`lib/model_registry.py`:** add `OLLAMA_TAGS_URL`, `normalize_model_name()`, `local_ollama_models()`, `model_presence()` (tests 1–14 first). Pure/offline except `local_ollama_models()`'s own HTTP call, which the tests mock.
2. **`lib/health_checks.py`:** add `_ollama_tags_remote(host)` (SSH probe, mirrors `_run_sync_log_remote`) and `_parse_ollama_tags(text)`, then `check_models_installed(reachability=None, reg=None, local_models=None, remote=None)` (tests 15–23 first).
3. **`lib/health_checks.py`:** add `check_profile_unknown_machines(directory=None)`, using `project_profile.all_profiles()` and `machine_profile._load_registry()` / `registry_id()` (tests 24–29 first).
4. Register both in `default_checks()`: `("models:installed", "Models installed for every capability", lambda: check_models_installed(reach), CROSS_MACHINE_BUDGET_S)` and `("profile:unknown-machines", "Project profiles name real machines", check_profile_unknown_machines, CHECK_BUDGET_S)`.
5. Apply the owner's answer to **model-fix**: either re-pull the two models on mac-mini-1 and verify `ollama list` shows them (Option A), or edit `config/models.json`'s `capabilities` plus the three asserts/docstrings in `logic_auditor.py`/`competing_ideas.py` (Option B).
6. Run `lib/model_registry.py check` and the new `check_models_installed()` locally against the real (post-fix) Ollama state on this machine to confirm it reports green, not just in mocked tests.
7. `CONTEXT.md`: append to the "Health monitoring" section (after the Numeric-anomaly bullet, before "## Entity IDs") a one-line rule — *"a config entry that names a resource has a health row that probes it"* — and name the two new checks (`models:installed`, `profile:unknown-machines`) as its first two instances.
8. Note in the PR description that PR `#1370` (ticket `#501`) is open on the same three paper-dive files, and that `#563`/`#1212` own the eventual model-choice benchmark this ticket deliberately doesn't run.
9. Run the full existing `lib/tests/test_model_registry.py` and `lib/tests/test_health_checks.py` suites plus the new tests, and the whole Python suite, before calling this done.
Now I have a complete picture. Let me write the plan.

## North-star fit

**Reuses:** the `chat_fn=None → real-path` branch already in every paper-dive function (`logic_auditor.classify_paper_type/extract_structure/judge_extraction/check_inference_validity`, `competing_ideas.classify_stance`, `argument_mapper.extract_core_claim`) — I add the availability check only inside that branch, never at import time, so injected-`chat_fn` unit tests stay network-free exactly as they are today. I reuse `model_registry.model_present()` and `normalize_model_name()` (added by #1211/PR #1385, already merged and tested) instead of re-deriving tag-matching rules, and I reuse `disk_reclaim.py`'s established "state the fix, don't auto-act" posture (its `delete_with_confirmation` pattern) by choosing a plain, actionable error over silent auto-pulling. `health_checks._query_ollama_models_local()`'s urllib call becomes a one-line delegate to a new `model_registry.list_installed()`, collapsing what would otherwise be a third near-duplicate of the same "query localhost:11434/api/tags" logic (bench.py's `_ollama_available`, health_checks.py's own, and the one this ticket needs) — the third-use-case bar `feedback-composability-principle` sets, so I extract now rather than duplicate again; I leave bench.py's own copy untouched since rewriting an already-tested, differently-shaped function is unnecessary risk for this ticket.

**Why simplest sufficient:** the ticket offers two options for the missing-model case ("pull it ... and asking first" or "fall back to a stated alternative"). I'm building the second, in its plainest form: a clear exception naming the capability, the missing model, its size, and the exact `ollama pull <model>` command — no interactive confirm/auto-pull machinery, no silent model substitution. That's strictly less code, has no "who answers the prompt in a headless pipeline run" problem, and can't regress into the exact failure the ticket forbids (quietly running the 14b judgment step on 7b). This also matches the owner's 2026-11-10 comment reclassifying the big "which model for every job" question as a cross-ticket research effort (with #1210/#1212, due M3 2026-11-27) — I do not attempt a live Ollama sweep in this ticket; `select_model.py --candidates` stays the explicit escape hatch for whoever runs that investigation next. This scoping also directly targets why this ticket has failed 3+ automated attempts already: every one of them tried to also run the live multi-GB-model sweep inside the same change, and timed out.

**Resources:** no network calls move to import time (several previous attempts' tests broke by accidentally requiring live Ollama just to `import logic_auditor`); no caching layer added for the availability check — a localhost GET costs single-digit ms, trivial next to the LLM calls it's gating, so a cache would be machinery solving a non-problem (Watts check).

**Phone-OS / capability:** none directly; this is a reliability fix for an existing local-model tool, not new user-facing surface.

**More capable or more passive:** more capable — today a deleted model produces a raw `HTTPError: 404` deep in `ollama_chat`, or (for the benchmark/14b override) nothing checks real availability at all, so a silently-wrong result is possible. After this, the failure is a one-line, actionable message naming the fix.

## Tests to write first

Against the real collaborator (Ollama's actual `/api/tags`/`/api/chat` HTTP shape) is impossible to require in CI, so all new tests mock at the function boundary (`model_registry.list_installed`, `model_registry.ensure_installed`, `ollama_chat`) the same way every existing test in this codebase already does — never mocking lower than that boundary where it would hide Ollama's real response shape, which is why the malformed-response tests (8–9 below) still exercise the real JSON-parsing code path.

**`lib/tests/test_model_registry.py`:**
1. `test_ensure_installed_raises_model_unavailable_when_missing` — mocked `list_installed` omits target model → `ModelUnavailableError`, message contains model name, size_gb (9.0 for 14b), and `ollama pull qwen2.5:14b`.
2. `test_ensure_installed_passes_when_present` — no raise.
3. `test_ensure_installed_raises_ollama_unavailable_when_server_down` — mocked `list_installed` returns `None` → distinct `OllamaUnavailableError`, message doesn't claim "not installed" (dependency-down ≠ model-missing, different fixes).
4. `test_ensure_installed_handles_tag_variants` — e.g. `qwen2.5:3b-instruct-q4_K_M` satisfies `qwen2.5:3b` (reuses `model_present`).
5. `test_ensure_installed_unregistered_model_reports_unknown_size` — model not in `models.json` at all → message says size is unknown instead of crashing on `None`.
6. `test_ensure_installed_never_mutates_registry` — success and failure paths both leave `models.json` byte-identical (it's a read-only check).
7. `test_resolve_or_raise_returns_model_when_available`.
8. `test_resolve_or_raise_propagates_model_unavailable_naming_configured_model`.
9. `test_resolve_or_raise_unknown_capability_raises_keyerror_not_model_unavailable` — bad config vs. missing model are different failures, must not be conflated.
10. `test_list_installed_returns_none_on_malformed_top_level_response` — mocked HTTP body is a JSON list, not an object → `None`, no `AttributeError` escapes (misuse: Ollama itself returns garbage).
11. `test_list_installed_skips_entries_missing_name_key` — one entry dict has no `"name"` → doesn't crash, returns the rest.
12. `test_two_consecutive_ensure_installed_calls_each_reflect_current_state` — first call mocked "present", second mocked "now missing" (simulating a model deleted mid-run / repeats) — second raises; confirms no hidden caching papers over a stale verdict.
13. `test_health_checks_query_ollama_models_local_delegates_to_list_installed` — behavior-preserving regression check for the refactor in `health_checks.py` (point 14).

**`skills/paper-dive/scripts/tests/test_logic_auditor.py`:**
14. **Fix (not new):** `test_judge_extraction_uses_14b_override_for_benchmark_when_no_chat_fn_given` and `test_judge_extraction_uses_default_7b_for_non_benchmark_types` (lines 336, 356) — add `monkeypatch.setattr(model_registry, "ensure_installed", lambda *a, **k: None)` so they test model *selection*, not live Ollama/registry state (this is the exact test class that broke on every prior attempt).
15. `test_judge_extraction_benchmark_raises_when_14b_missing_even_if_7b_present` — mock `ensure_installed` to raise only for `"qwen2.5:14b"`; call with no `chat_fn` on a `"benchmark"` paper type → `ModelUnavailableError` naming 14b; the `ollama_chat` mock must never be called (core ticket requirement: never fall through to 7b).
16. `test_judge_extraction_empirical_raises_when_7b_missing`.
17. `test_classify_paper_type_raises_when_14b_missing_no_chat_fn`.
18. `test_extract_structure_raises_when_3b_missing_no_chat_fn`.
19. `test_check_inference_validity_raises_when_14b_missing_no_chat_fn`.
20. `test_classify_paper_type_extract_structure_judge_extraction_check_inference_validity_with_injected_chat_fn_never_touch_registry` — one parametrized test (or 4 small ones): monkeypatch `model_registry.ensure_installed` to raise `AssertionError` if called; every function, given a real `chat_fn`, must never call it.
21. `test_importing_logic_auditor_makes_no_network_call` — reload the module with `model_registry.list_installed` patched to raise if invoked; import must succeed untouched (regression guard for the "tests need live Ollama just to import" failure class).

**`skills/paper-dive/scripts/tests/test_competing_ideas.py`:**
22. `test_classify_stance_raises_when_7b_missing_no_chat_fn`.
23. `test_classify_stance_with_injected_chat_fn_never_touches_registry`.

**`skills/paper-dive/scripts/tests/test_argument_mapper.py`:**
24. `test_extract_core_claim_raises_when_3b_missing_no_chat_fn`.
25. `test_extract_core_claim_with_injected_chat_fn_never_touches_registry`.

**`skills/paper-dive/scripts/tests/test_continuity_checker.py`:**
26. `test_continuity_model_resolved_via_registry_not_hardcoded` — `CONTINUITY_MODEL == model_registry.resolve_capability("local-inference-large")[0]` (closes the one call site that bypassed the registry entirely).
27. `test_classify_continuity_raises_when_14b_missing_no_chat_fn`.
28. `test_classify_continuity_with_injected_chat_fn_never_touches_registry`.

**New `bench/tests/test_bench_model_defaults.py`** (no existing file covers CLI defaults — checked):
29. `test_default_ollama_model_is_an_installed_model` — `--ollama-model` default is `qwen2.5:3b`, not a deleted model.
30. `test_select_model_default_ladder_excludes_deleted_models` — `select_model.DEFAULT_LADDER`'s first entry is `("ollama", "qwen2.5:3b")`; no `7b`/`14b` entries by default.
31. `test_select_model_candidates_flag_still_allows_7b_14b` — explicit `--candidates ollama:qwen2.5:7b,ollama:qwen2.5:14b` still parses correctly (the "require the flag" escape hatch keeps working).
32. `test_bench_ollama_preflight_passes_with_default_model_when_only_3b_installed` — mocked model list contains only `qwen2.5:3b`; `main()`'s preflight with no `--ollama-model` override no longer exits (today it does, against the deleted 7b default).

Not outward-facing (no website form, endpoint, or untrusted text reaches a model here — prompts are built from already-ingested paper abstracts, unrelated to this ticket), so no Attacks list.

## Task List

1. `lib/model_registry.py`: add `ModelResolutionError`, `ModelUnavailableError(model, size_gb)`, `OllamaUnavailableError(model)`; add `list_installed() -> list[str] | None` (the localhost `/api/tags` query, tolerant of a non-dict body and entries missing `"name"`); add `ensure_installed(model, reg=None) -> None` and `resolve_or_raise(capability, reg=None) -> str`. Tests 1–12 first.
2. `lib/health_checks.py`: change `_query_ollama_models_local()` to `return model_registry.list_installed()`. Test 13.
3. `skills/paper-dive/scripts/logic_auditor.py`: in `classify_paper_type`, `extract_structure`, `check_inference_validity`, call `model_registry.resolve_or_raise(<capability>)` inside the existing `chat_fn is None` branch instead of referencing the module constant directly; in `judge_extraction`'s `chat_fn is None` branch, call `model_registry.ensure_installed(model)` on the already-selected `JUDGMENT_MODEL_OVERRIDES`-resolved model before building the real `chat_fn`. Fix tests 336/356 first, then add 15–21.
4. `skills/paper-dive/scripts/competing_ideas.py`: same lazy-check pattern in `classify_stance`. Tests 22–23.
5. `skills/paper-dive/scripts/argument_mapper.py`: same in `extract_core_claim`. Tests 24–25.
6. `skills/paper-dive/scripts/continuity_checker.py`: replace the hardcoded `CONTINUITY_MODEL = "qwen2.5:14b"` with `model_registry.resolve_capability("local-inference-large")[0]` (needs the existing `sys.path.insert(...lib...)` + `import model_registry`, matching the other three files), plus the same lazy check in `classify_continuity`. Tests 26–28.
7. `bench/bench.py`: change `--ollama-model` default to `"qwen2.5:3b"`. Test 29, 32.
8. `bench/select_model.py`: change `DEFAULT_LADDER`'s first entry from `("ollama", "qwen2.5:7b")`/`("ollama", "qwen2.5:14b")` to `("ollama", "qwen2.5:3b")` only (drop the 7b/14b default entries; `--candidates` remains the way to test them). Tests 30–31.
9. Run the full mocked suite (`~/.agents/venv/bin/python -m pytest -q`, whole repo) and the dashboard suite (`cd dashboard && npx vitest run`) — zero live Ollama/network calls required — and confirm green before finishing.
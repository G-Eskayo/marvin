## North-star fit

**Reuses, before adding anything new:**
- `bench/bench.py`'s `_ollama_available()`, timing/aggregation (`aggregate_runs`, `fmt_table`) and infra-error-vs-real-failure distinction (`INFRA_ERROR_MARKERS`/`infra_error`) — same shape, extended rather than duplicated. `select_model.py` already establishes the precedent of a sibling script that imports `bench.py`'s helpers instead of editing `bench.py`'s own CLI surface; this spike's runner does the same.
- `run_once_ollama()` (`bench/bench.py:133`) explicitly returns `None` for `type: "fs"` tasks ("fs tasks require tool use") — confirming the existing Ollama runner cannot drive a real-repo coding task at all. That's the actual gap this ticket fills; it isn't something to reuse, it's the reason new code is needed.
- `lib/build_type_measure.measure()` + `lib/evidence_capture.capture_test_results()` for "did the gate pass" — this is the exact existing pattern for a mechanical pass/fail test-suite gate (already used for build-type tickets), including the documented fixed-baseline/fixed-current-set discipline and the two-separate-counts (`tests_passed`/`tests_failed`) fix for the fraction-blindness bug found 2026-10-01.
- `lib/metrics_registry.compare()` (pure function, no I/O) as the gate verdict: `compare(subsystem, baseline, current)["passing"]` is `True` only on verdict `"improved"` — `"unchanged"` never passes. This gives "did opencode's patch actually fix the thing" for free, battle-tested, without inventing a new comparison rule. `METRICS_DIR` already resolves through `instance.path(...)` (ADR 0071), so calling `compare()` directly (no `record()`/`latest()` calls) keeps this spike's gate check pure and avoids any instance-repo coupling.
- `EnterWorktree`/`ExitWorktree` — the existing sandbox-isolation pattern for the MR pipeline (CONTEXT.md "MR pipeline / Sandbox isolation") — reused for isolating each real-ticket checkout, instead of a new ad hoc `git worktree` wrapper or a full VM.
- `bench/RESULTS.md`'s existing "Run N — date (title)" + table + Findings/Caveats format — reused verbatim for the write-up, no new report format.
- `bench/tasks/<id>/task.json` + `prompt.md` convention (`bench/README.md`'s "Task format") — extended with one new `type` value (`"real-ticket"`) rather than inventing a parallel data format.
- `docs/adr/0030`'s `dontAsk` + explicit `--allowedTools` headless-execution pattern — extended (new entries), not replaced, for whatever `opencode`/`ollama`/`powermetrics` access this needs.

**Why this is the simplest sufficient approach:** the measurement machinery (token/cost/time capture, infra-error tagging, aggregation, reporting) already exists in `bench.py`; the test-pass/fail gate already exists in `build_type_measure`/`metrics_registry`; sandboxing already exists via `EnterWorktree`. The only genuinely new code is (a) a thin runner that drives `opencode` instead of `claude`/`ollama`'s chat API against a real repo checkout instead of a synthetic `files/` fixture, and (b) a powermetrics sampler (`energy_apple.py`, named to match the OpenJarvis reference the ticket cites) — because nothing in this repo measures energy today. Everything else is composition of existing primitives.

**Tokens:** this spike costs zero Claude tokens for the candidate runs themselves (Ollama is local/free) — the only Claude spend is this planning pass and whatever the pipeline's own planning/verification calls cost, same as any ticket. It spends real Mac-mini wall-clock/power running `powermetrics` and a 3B (or larger, pending Decision 1) local model five times over, which is the deliberate point of measuring it.

**Phone-OS direction:** neutral-to-positive — it's exploratory infrastructure measurement (ADR 0071's instance/engine split and the M3 subscription-sunset planning), not a user-facing capability.

**More capable or more passive:** neither directly — no end-user-facing behavior changes. It gives Gil (and future dispatch decisions) real numbers instead of guessing whether local models are viable for small tickets, which is itself the thing that lets good *delegation* decisions get made later (an "is the human more capable" test doesn't really apply to a measurement spike).

**Stated ticket fit vs. code:** the ticket says "reuse the same harness as #645" — but #645 is still open with unanswered Decisions (`marvin-default`/`claude-cli-plain` profiles don't exist yet). What's actually reusable from #645 right now is `bench.py`'s general measurement/scoring shape, not a built profile pair. I've corrected for that above rather than blocking on #645.

## Tests to write first

No "How we'll try to break it" section exists on #674 itself, so this list is derived from ADR 0063's standard misuse categories applied to the two new pieces of code (a real-ticket opencode/Ollama runner, and `energy_apple.py`), plus the real collaborators involved (Ollama, `opencode`, `powermetrics`, git worktrees, `metrics_registry.compare()`). Tested against the real collaborator wherever a mock could hide its rules (real localhost Ollama check, real subprocess timeout/kill, real `git worktree`, real `compare()` call) — mocked only where the real collaborator (`opencode`, `powermetrics`, a pulled 7B/14B model) isn't guaranteed present in CI.

1. `test_ollama_unreachable_marks_infra_error` — Ollama server down → tagged `infra_error`, never a fabricated `0.0`/gate-fail.
2. `test_model_not_pulled_fails_clearly` — Ollama up, requested model absent → error names the model + pull command (same shape as `_ollama_available`'s existing message), no silent fallback to whatever model *is* present.
3. `test_opencode_binary_missing_fails_loud` — `opencode` not on `PATH` → clear `spawn_error`, distinct from "ran, produced a bad patch."
4. `test_opencode_timeout_is_enforced` — a real subprocess stand-in that hangs past the configured timeout is actually killed (not left running), via the real kill path, not a mocked `Popen`.
5. `test_opencode_crash_distinguished_from_gate_failure` — non-zero exit / empty stdout is `spawn_error` (harness broke), never scored as "model attempted it and failed the gate."
6. `test_empty_or_title_only_prompt_handled` — a ticket body that's blank or title-only doesn't crash the runner.
7. `test_oversized_prompt_handled_not_corrupted` — a prompt far exceeding the model's context is truncated/rejected with a stated reason, not silently fed in a way that corrupts grading.
8. `test_unknown_base_sha_fails_loud` — bad `base_sha` in a `task.json` raises before any opencode run starts, never silently checks out `HEAD`.
9. `test_worktree_cleaned_up_on_success_and_on_crash` — both paths leave no leftover worktree/branch, exercised against the real `git worktree`/`EnterWorktree` mechanism.
10. `test_gate_requires_improvement_not_just_unchanged` — real `metrics_registry.compare()` call: a current snapshot identical to baseline (a no-op patch) must not pass; only a genuine `tests_failed` drop / new passing test (no new failures) passes.
11. `test_gate_fails_on_any_new_regression` — current snapshot with a higher `tests_failed` than baseline fails the gate even if it also incidentally fixed the target test (mixed verdict never passes).
12. `test_energy_sampling_is_serialized` — the runner refuses/queues a second energy-sampled run while one `powermetrics` sampler is still active, so two runs' power windows never overlap and double-count.
13. `test_powermetrics_unavailable_reports_none_not_zero` — no sudo access → energy field is `None` with a recorded reason, never a fabricated `0.0`.
14. `test_powermetrics_process_reaped_on_early_exit` — opencode exits immediately/crashes → the background sampler process is still terminated, not left orphaned.
15. `test_fails_clearly_off_mac_mini` — dispatched on a machine without the model pulled/Ollama reachable → a clear "wrong machine" message, not all-zero/garbage results.
16. `test_repeated_run_is_independent` — running the same ticket twice: each run's baseline is freshly re-derived from `base_sha`, never cached/leaked from a prior run.
17. `test_ticket_selection_rejects_out_of_scope_candidate` — a candidate PR touching files outside the declared docs/one-line-bug/test-addition scope is rejected by the selection step, not silently included among the 5.

## Decisions

<!-- marvin:decisions -->
### local-model: Which local model(s) does this spike test?
- [ ] A: `qwen2.5:3b` only — the only model actually present on the Mini today (#563: 7b/14b were deleted 2026-10-21). Fastest, no new download, but likely too weak to tell us much about a realistic "small tickets go local" lane.
- [ ] B: Temporarily re-pull `qwen2.5:7b` (4.7 GB) for this spike only, closer to the ~9B class the ticket's own "Why" section cites from the OpenJarvis paper, then delete it again afterward.
- [ ] C: Both A and B, reported side by side.

### headless-access: How does the headless pipeline agent get to run `opencode`/`ollama`/`powermetrics`?
Today's execution allowlist (ADR 0030) only covers `git status*`, `pytest*`, `npm test*`/`install*`, `npx vitest run*` — none of `ollama`, `opencode`, or `powermetrics` (which needs root). Permissions/allowlist changes are a core area that always waits for Gil (never auto-merged).
- [ ] A: Add scoped allowlist entries (`Bash(ollama *)`, `Bash(opencode run*)`, `Bash(sudo powermetrics*)`) plus a sudoers `NOPASSWD` rule scoped exactly to the `powermetrics` binary.
- [ ] B: Drop energy measurement from this pass (gate/tokens/time only) so no sudo/allowlist change is needed; revisit energy later as its own ticket.
- [ ] C: Run this spike as a live/interactive session instead of headless dispatch, so normal permission prompts apply and nothing needs to change in the dontAsk allowlist.

## Task List

1. Pick the 5 tickets. Query merged PRs (`gh pr list --repo G-Eskayo/marvin --state merged --json number,title,additions,deletions,changedFiles,files,mergedAt`), filter to small, single-scope, docs-fix / one-line-bug / test-addition diffs (starting shortlist found during planning: #656, #627 docs-only; #541, #414 one/two-line bugfixes — verify these and/or newer merges still fit at execution time), and for each resolve the merge commit's first parent as `base_sha`.
2. Extend the `bench/tasks/<id>/task.json` schema with `type: "real-ticket"` (`pr_number`, `repo`, `base_sha`); write one `task.json` + `prompt.md` (the original issue/PR body) per selected ticket under `bench/tasks/task-0XX-<slug>/`.
3. Resolve Decision `local-model` and (if needed) pull/verify the chosen Ollama model(s) are present on the Mac mini.
4. Resolve Decision `headless-access`; apply the agreed allowlist/sudoers change (if A) before any headless run, or drop energy (if B), or run interactively (if C).
5. Write `bench/lib/energy_apple.py`: start/stop a `powermetrics` sampler around an arbitrary subprocess call, parse CPU/GPU/ANE power into joules/Wh over the sampled wall time; returns `None` (not `0.0`) with a reason when sampling isn't available. Covers break-it cases 12–14.
6. Write the real-ticket runner (new sibling script, e.g. `bench/run_local_coding_spike.py`, importing from `bench.py` and `lib/build_type_measure.py`/`lib/evidence_capture.py`/`lib/metrics_registry.py`, following `select_model.py`'s existing import-don't-edit pattern): per ticket — `EnterWorktree` at `base_sha` → `build_type_measure.measure()` as baseline → invoke `opencode` headlessly against the chosen Ollama model (read-only network beyond `localhost:11434`, no push credentials in the worktree) with a hard timeout → `build_type_measure.measure()` again → `metrics_registry.compare()` for the gate verdict → wall time from the subprocess call → energy from step 5 → `ExitWorktree`. Covers break-it cases 1–11, 15–17.
7. Write the 17 tests above against this runner and `energy_apple.py` (real localhost Ollama check, real subprocess timeout/kill, real `git worktree`, real `compare()` calls; mocked only where `opencode`/a pulled large model/`powermetrics` genuinely can't be assumed present).
8. Run all 5 tickets once each (raw JSON to `bench/results/`, gitignored, matching existing convention), then append one new "Run N — 2026-10-26 (local coding assistant spike, opencode + Ollama)" section to `bench/RESULTS.md`: a table (ticket, gate pass/fail, tokens, wall time, energy) per the existing report format, plus a Findings section stating which ticket kinds (if any) look viable for a "small tickets go local" lane, and Caveats (model size tested, single-run noise, machine-specific).
9. If Decision `local-model` chose B or C, delete the temporarily-pulled model afterward and note that in RESULTS.md's Caveats.
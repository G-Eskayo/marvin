## North-star fit

**Reuses:** `bench/bench.py`'s existing task/profile/runner abstraction (`--runner claude|ollama`, `run_once`/`run_once_ollama`, `aggregate_runs`, the `results/*.json` + `RESULTS.md` Run-N append convention) rather than a new harness — exactly what #645 already established as the rule ("reuse `~/.agents/bench`... It's a new pair of profiles, not a new harness"). The "gate" check reuses `lib/evidence_capture.capture_test_results`/`parse_test_output` (marvin's own real pytest/vitest parser), not bench's synthetic substring scorer. Git-checkout-at-a-past-commit isolation reuses `sandbox_orchestration._create_worktree`/`_cleanup_worktree` (already collision-hardened from two real incidents, #20/#21) instead of writing new worktree code. Missing-tool handling reuses `project_profile.py`'s `EnvMissing` pattern. Model provenance reuses `lib/model_registry.py` (register before pulling anything).

**Simplicity:** this is CONTEXT.md's own documented **build-type ticket** shape (new capability, no prior baseline) — the gate is mechanical (tests pass, the script runs) per the already-decided split between build-type and tunable-subsystem tickets. I treat it that way explicitly, because the alternative reading — that the *verify loop* should only pass once the local model's replayed tickets look good — is a likely cause of the second failed attempt ("did not reach a passing comparison after 3 iterations"): a local 3b/7b model losing to Sonnet is the expected, reportable *result* of this spike, not a defect to iterate away.

**Tokens:** spends real tokens (5 real-ticket replays × 2 runners, plus their own unit tests) but is bounded and one-shot ("no adoption yet"); saves tokens long-term only if the recommendation says yes and a lane gets built later — this ticket doesn't spend on hypothetical future generality.

**Phone-OS / capability:** doesn't touch the phone-OS vision directly; it's pure measurement. It leaves the *system* more capable (an honest answer to "can local models carry small tickets") without the user doing less — no behavior changes until the recommendation is acted on.

**Likely root cause of both prior failures, found while reading the code, not guessed:**
1. **Timeout (1200s):** nothing in this repo touches `powermetrics` today (confirmed — no hits anywhere in `~/.agents`). `powermetrics` requires root; `sudo powermetrics` with no pre-authorized NOPASSWD rule blocks on an interactive password prompt that never arrives in a headless `-p` session — exactly the shape of a hang that eats a 1200s wall-clock budget. This must be designed to fail fast, never block.
2. **"Must-fix issues" after 3 iterations:** most plausible explanation given the build-type framing above is the executor treating "the local model should produce a good result" as the pass condition instead of "the new measurement code works and runs cleanly." The plan below pins the gate to the latter.

---

## Tests to write first

No "How we'll try to break it" section exists on #674 itself, so this list is the full misuse sweep against this build:

1. **Bad/malformed input** — `task.json` missing required fields (`base_ref`, `verify_cmd`); a non-existent/garbage git SHA as `base_ref`; a `verify_cmd` that references a binary that doesn't exist.
2. **Empty input** — empty `prompt.md`; a replay ticket whose original diff touched zero files.
3. **Huge/malformed input** — a prompt/diff large enough to exceed a 3B/7B model's context window; malformed `powermetrics` plist/text output (truncated, non-numeric, empty) must not crash the integrator.
4. **Each dependency failing:**
   - Ollama server down / target model not pulled → existing `_ollama_available()` preflight, reused, must fire before any opencode subprocess spawns.
   - `opencode` binary missing → `EnvMissing`-style clean failure, not a traceback.
   - `powermetrics` missing, **or present but no passwordless sudo** → energy returns `None`/"unavailable" immediately (direct regression test for failure #1 above — never actually shell out to `sudo powermetrics` without first probing `sudo -n true`).
   - `gh`/GitHub unreachable while picking the 5 replay tickets → fails loud, doesn't silently fall back to fewer tickets.
5. **Repeats/concurrency** — two replay runs started against the same ticket at once, or a prior run's worktree+branch left stale (the exact #20/#21 collision bug `_create_worktree` already fixes) — must not collide; reuse, don't reimplement, that fix.
6. **Wrong permissions/machine** — running on a machine without `ollama`/`opencode` installed raises the same `EnvMissing` shape `project_profile.py` already uses elsewhere, so the pipeline can tell "wrong machine" from "real failure."
7. **Stale state** — a half-finished worktree/branch from an interrupted previous replay must be cleaned and reused correctly on the next run (same fixture as #5).
8. **A person's mistakes** — a typo'd `--ollama-model` name must hit the existing `_ollama_available()` check and fail with the clear message it already produces, not silently substitute another model.
9. **Gate-scoring integrity** — the ticket's *original* verify command is run once against the unmodified pre-fix checkout (baseline) and once after the model's attempt, scored separately — so a test that was already flaky/failing before any model touched it is never misattributed as "the local model broke it."
10. **RESULTS.md append-only** — running the spike twice must append a new dated Run section and leave all 1172 existing lines untouched (regression test against this specific, long-lived file).
11. **Real collaborator, not mocked** — `_ollama_available`, the `opencode` subprocess, and `powermetrics` are exercised against the real binaries guarded by availability probes (skip when absent, never mock their pass/fail rules) — matches the existing pattern already in `bench.py`.

## Decisions

<!-- marvin:decisions -->
### model: Which local model(s) does the spike use?
- [ ] A: `qwen2.5:3b` only — already on the Mini, zero pull/disk cost, but far smaller than the 9B model OpenJarvis's paper measured losing 25–39 points
- [ ] B: Pull one closer in size to OpenJarvis's 9B test (e.g. `qwen2.5:7b`, previously deleted per #563) specifically for this spike, registered in `config/models.json` first
- [ ] C: Run both A and B and report separately

### energy: How should missing passwordless sudo for `powermetrics` be handled?
- [ ] A: Hard prerequisite — owner sets up a narrow NOPASSWD sudoers rule for the `powermetrics` binary only, before this runs; the script errors clearly if it's missing
- [ ] B: Graceful degradation — if passwordless sudo isn't available, skip the energy column for that run and say so in RESULTS.md, rest of the spike still runs
- [ ] C: Both — try A's probe first, fall back to B if it's not configured

### tickets: How are the 5 past tickets selected?
- [ ] A: Filtered automatically (`gh pr list --state merged`, smallest diffs + docs/test/bugfix labels), picked without further review
- [ ] B: Filtered automatically, then the owner reviews the shortlist before locking it in
- [ ] C: Owner hand-picks the 5 PR numbers directly

### scope-risk: If opencode structurally can't drive real file edits through this local model (no usable tool-calling), what happens?
- [ ] A: Report that as the finding (0/5 attempted) — it's a valid, honest spike result
- [ ] B: Fall back to a context-injection-only comparison (like `bench.py`'s existing `run_once_ollama`, QA-only) so there's at least a partial number, and note the fs-task gap explicitly

## Task List

1. Preflight on the Mac Mini: confirm `opencode` and `ollama` are installed and the chosen model(s) from Decision `model` are pulled; register any newly-pulled model in `config/models.json` via `lib/model_registry.py` before downloading.
2. Add narrowly-scoped entries to `lib/sandbox_orchestration.py`'s `_EXEC_ALLOWED_TOOLS` for `ollama`, `opencode`, and the energy script's `powermetrics`/`sudo -n` probe — matching the file's existing comment/format style, no wider than this ticket needs.
3. Write tests first for `lib/energy_apple.py` (new): no-sudo path returns promptly with `None`/reason (regression test for the suspected timeout cause), missing-binary path, malformed-output path, real-sudo-available path (skipped, not mocked, when unavailable).
4. Build `lib/energy_apple.py`: samples `powermetrics` CPU/GPU/ANE power for a subprocess's duration, integrates watts × wall-seconds → joules, probing `sudo -n true` before ever invoking `sudo powermetrics`.
5. Write tests first for `bench/bench.py`'s new pieces: malformed/missing `task.json` fields for the new `"replay"` type, worktree collision/stale-state reuse, baseline-vs-post-attempt gate separation, concurrent-run safety, RESULTS.md append-only behavior, huge/empty prompt handling.
6. Extend `bench/bench.py`: add task type `"replay"` (worktree via `sandbox_orchestration._create_worktree`/`_cleanup_worktree` at the ticket's pre-fix commit) and `--runner opencode`; `run_once_replay()` runs the chosen runner with the ticket's own description as the prompt, scores the gate via `evidence_capture.capture_test_results`, and wraps the run in `energy_apple`'s sampler.
7. Per Decision `tickets`: select and record 5 real merged small tickets as `bench/tasks/replay-NNN-*/{task.json,prompt.md}`, each pointing at its real pre-merge commit and real verify command.
8. Run all 5 through `bench.py --runner opencode --ollama-model <Decision model>` and through the existing `claude` runner for comparison; capture gate pass/fail, tokens, wall time, energy.
9. Append a new dated Run section to `bench/RESULTS.md` (matching the existing Run-N convention) with the data and a concrete recommendation on a "small tickets go local" lane and which ticket kinds qualify.
10. Update `last_used` in `config/models.json` for whichever model(s) were actually exercised.
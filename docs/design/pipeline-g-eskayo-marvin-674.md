## North-star fit

**Reuses before adding anything new:**
- `lib/project_profile.py:verify_dir` + `load_profile` — this *is* "the gate" (CONTEXT.md calls a build-type ticket's pass "mechanical: tests pass, build is clean" — exactly this function's `ok`/`kind`/`summary` return). I'll call it on each candidate's patched worktree instead of writing a second test-runner.
- `bench/bench.py`'s task-dir convention (`tasks/<id>/{task.json, prompt.md, files/}`, `load_task()`) and its `run_once_ollama`/`_is_infra_error`/`infra_error` pattern — proven way to tell "never actually ran" apart from "ran and failed."
- `bench/select_model.py`'s ascending-cost ladder (`qwen2.5:7b` first rung) for which local model to drive.
- `bench/RESULTS.md`'s existing "Run N — <date>" section format (Runs 1–2 already there) for where the write goes.
- `docs/agents/decisions-format.md` for the two real open questions below.

**What's genuinely new, and why it's still the simplest sufficient shape:** two small, general primitives, not one-off glue — a tiny Ollama usage-accounting proxy (`bench/lib/ollama_usage_proxy.py`) and a `powermetrics` sampler (`bench/lib/energy_apple.py`). Both exist because `opencode`, not `bench.py`, is the thing calling Ollama this time, so bench can't just read `eval_count` off its own request like `run_once_ollama` does — it has to watch the wire. Measuring at the Ollama boundary rather than trusting `opencode`'s own self-reported usage is "verified, not assumed." Neither is single-use: any future local-model spike reuses both.

**No pipeline change.** The ticket says "no adoption yet" — I'm not touching `config/models.json`, `lib/model_registry.py`, or adding a dispatch capability. Scope stops at measurement.

**Tokens:** spent now understanding the gate/harness so the build doesn't re-derive them; the spike itself runs on free local Ollama inference. The only cloud cost is the existing bench quota-preflight pattern if judge calls are used — reused, not duplicated.

**Phone-OS direction:** direct evidence toward "MARVIN becomes the OS of Gil's own phone" — a phone has no cloud-token budget most of the time, so whether a local lane can handle small tickets is a real precondition, not a tangent.

**User capability:** this is a measurement, not an automation that removes Gil's judgment — it answers "is there a small-tickets-go-local lane" so a later real decision isn't guessed. Net: more informed, not more passive.

**One fit-check against a recorded decision:** ADR 0071 lists "bench metrics" as **instance** state (meant to live in the private per-person repo, not the public engine). `bench/RESULTS.md` in this engine worktree still carries real historical run data today, un-migrated — so the ADR's intent and the ticket's explicit instruction ("write to `bench/RESULTS.md`") currently point in different directions. I'm following the ticket (current precedent, no PII, matches what's already committed) and flagging the mismatch rather than silently fixing or silently ignoring it — migrating bench metrics into the instance repo is its own ticket, not in scope here.

## Tests to write first

The ticket has no "How we'll try to break it" or Attacks section — it's an internal spike with no outward-facing surface (no endpoint, no untrusted input). Misuse cases derived for each new piece:

**Ticket-selection step**
1. Candidate PR has no linked issue / no issue body → skip with a stated reason, never silently use the PR title as the prompt.
2. Merge commit has more than one non-trivial parent (squash-of-a-merge) → base-commit resolution picks correctly or skips with a reason, never runs against the wrong baseline.
3. Fewer than 5 candidates match the size/kind filters → exits with a clear message, never ships a RESULTS.md section with fabricated or missing rows.

**`ollama_usage_proxy.py`**
4. Ollama unreachable when the proxy starts → that ticket's run is recorded as an infra error (reusing `_is_infra_error`), never scored as a real 0.
5. Upstream returns malformed/truncated JSON → that call logs zero usage and is flagged, doesn't crash the run.
6. Two tool calls land concurrently → both get counted, thread-safe, none dropped or double-counted.
7. Same ticket run twice (a retry) → usage log is per-run-scoped, never accumulates across runs.

**`energy_apple.py`**
8. No passwordless sudo for `powermetrics` → sampler fails closed, reports energy as "unavailable," never fabricates a number or blocks on a password prompt that can't arrive headless.
9. A stale `powermetrics` process survives a previous crashed run → start refuses or cleans it up rather than running two samplers that corrupt both readings.
10. `opencode` hangs → a hard timeout (matching bench's existing `task.get("timeout", 600)`) kills both the run and its sampler.

**Driver (`spike_opencode_ollama.py`) + gate reuse**
11. `opencode`'s patch leaves the worktree dirty/doesn't apply → `verify_dir`'s existing `error`/`env_missing` classification surfaces in the per-ticket row, never collapsed to a bare pass/fail.
12. Worktree directory not writable → same, surfaces as `env_missing`, not silently skipped.

**RESULTS.md writer**
13. Spike run twice → appends a new "Run N" section, never overwrites or duplicates a previous run's numbers.
14. Partial run (e.g. 3 of 5 tickets finish before a crash) → missing tickets are marked explicitly, never silently omitted.

## Decisions

<!-- marvin:decisions -->
### powermetrics-sudo: powermetrics needs root. How should the spike get it, fully headless on the Mini?
- [ ] A: Add a scoped NOPASSWD sudoers rule for `/usr/bin/powermetrics` only — reusable for future energy telemetry, but a standing root-level grant on the real Mini (not a disposable VM)
- [ ] B: Run this spike's driver by hand under `sudo` once; skip energy on any later unattended re-run until this is answered
- [ ] C: Skip energy measurement for this spike; report gate-pass/tokens/time only and mark energy as not measured

### opencode-install: opencode isn't on the Mini yet (only Ollama is, per the ticket). How should the spike install it?
- [ ] A: `npm install -g` (or brew) it unattended as part of the spike's setup step — a standing change to the Mini's global tool state
- [ ] B: Leave install to Gil; the ticket stays blocked on this step until he confirms it's present
- [ ] C: Install it scoped to this ticket's worktree only (e.g. `npx`), nothing persists on the Mini afterward

## Task List

1. Confirm real Mini state first: `ollama list` (which models are actually pulled — #563 found 7b/14b deleted 2026-10-21, contradicting `config/models.json`), `opencode --help`/its non-interactive run flags and usage-reporting shape, and whether `powermetrics` currently needs a password for this user. Record findings in the PR.
2. Build `bench/lib/ollama_usage_proxy.py` (threaded HTTP proxy in front of `localhost:11434`, logs per-call token counts to a per-run JSONL) + tests for cases 4–7.
3. Build `bench/lib/energy_apple.py` (start/stop a `powermetrics` sampler, reduce samples to Joules) + tests for cases 8–10 against a fake subprocess.
4. Build the ticket-selection step: query merged `G-Eskayo/marvin` PRs, filter to small diffs across docs-fix/one-line-bugfix/test-addition kinds (favor diversity across the three named kinds, fill remaining slots by size), resolve each PR's linked issue body and true single-parent base commit, package as `bench/tasks/spike-opencode-ollama/<ticket-id>/{task.json,prompt.md}` reusing bench's existing task-dir shape. Tests for cases 1–3.
5. Build `bench/spike_opencode_ollama.py`: per task — `git worktree add` at the base commit, start both samplers, run `opencode` against the proxy pointed at the chosen Ollama model, stop samplers, call `project_profile.load_profile("marvin")` + `verify_dir` on the worktree for gate pass/fail, record wall time, clean up the worktree regardless of outcome. Tests for cases 11–12 plus a hung/crashed-`opencode` fake.
6. Build the `bench/RESULTS.md` section writer (new "Run N — opencode+Ollama spike" table + one-paragraph recommendation, same format as Runs 1–2). Tests for cases 13–14.
7. Resolve the two Decisions above with Gil before step 8 runs unattended.
8. Run the real spike end to end on the Mac Mini (5 tickets, both samplers live, real `opencode`/Ollama) and commit the resulting `bench/RESULTS.md` update and raw per-run JSON under `bench/results/`.
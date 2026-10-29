Now I have what I need to write the plan.

## North-star fit

**Reuses:** `bench/retrieval_eval.py` (marvin#705) as the structural template — a standalone, measured eval script with a private fixture of real cases, no live dependency baked into the gate, writing one methodology+table+caveats section to `bench/RESULTS.md`. `bench/bench.py`'s `_ollama_available()` preflight-check pattern and `run_once_ollama()`'s Ollama `/api/chat` plumbing (`OLLAMA_BASE`, JSON POST, timeout handling) for talking to the local model. `lib/instance.py`'s `instance_dir()`/`path()` for anything Mac-Mini-specific (model choice, raw per-run transcripts) — ADR 0071 ("configuration lives in the private instance, never the engine", ADR 0073) and `deliverable_location_guard.py`'s existing enforcement of that split. No existing code drives `opencode` or reads `powermetrics`; those two pieces are new, kept as small, mockable wrappers (same shape as `_ollama_available`), not a new framework.

**Simplest sufficient approach:** one new script (`bench/local_agent_spike.py`) that, per ticket: checks out the historical pre-merge commit into a throwaway worktree, runs `opencode` against Ollama with a time budget, scores gate-pass against *only* the test file(s) the original PR touched (not the full suite — see Decision `gate-scope` below), samples `powermetrics` in the background the way OpenJarvis's `telemetry/energy_apple.py` does, and appends one table to `bench/RESULTS.md`. No new abstraction layer, no change to `bench.py` itself (the existing `--runner ollama` path is qa-only by design and is left alone).

**Tokens:** spent once, off the hot path — this is a measured one-time spike per the ticket ("no adoption yet"), not a recurring job. Keeping the live run *outside* the automated verification gate (Decision `verify-scope`) is what stops this ticket from re-burning a 1200s gate budget a fifth time.

**Phone-OS / capability:** directly feeds M3 (post-subscription local-model lane) and M1b — it's the one piece of evidence needed to decide whether small tickets can run on-device, which is a precondition for MARVIN working without a paid API at all.

**More capable or more passive:** this leaves Gil more capable — it turns "will local models handle small tickets" from a guess into five measured data points plus a stated recommendation he can act on, without silently adopting anything (explicitly "no adoption yet").

## Why this ticket has failed 4 times (read before building)

1. Timeout (1200s) — twice. 2. "3 iterations, code review found must-fix issues." 3. **pytest collection crashed across five unrelated files** (`test_sandbox_orchestration.py`, `test_simulator_capture.py`, `test_ticket_claim.py`, `test_ticket_coordination.py`, `test_ticket_pipeline.py`) — a prior attempt broke global collection, almost certainly by adding a top-level import or fixture that something else transitively imports. This is the clearest signal: **new code must be new files under `bench/`, must not touch `conftest.py` or shared `lib/` modules, and must not run live external tools (`opencode`, a real Ollama call, `sudo powermetrics`) at import time or in anything pytest collects.** The timeouts are explained by the same root cause as the issue itself documents (#563): running a real tool-using agent against a local model, 5 times, has no fast path — that work must happen *outside* the fast automated gate, which is why `verify-scope` is a Decision below, not a guess.

## Tests to write FIRST

The ticket has no "How we'll try to break it" section (it's a Spike, not a build ticket — no AC/attacks template was applied). Applying the standard misuse list myself, scoped to what's actually new:

1. `_ollama_available`-style preflight for **opencode availability** (`shutil.which("opencode")` missing) → script reports a clear skip/error, never a stack trace, never scores 0.0 as if the agent tried and failed.
2. Ollama server down / model not pulled → same existing `_ollama_available()` check reused verbatim; test that the spike calls it before spending any wall-clock time.
3. **Bad/empty/huge/malformed opencode output**: opencode process exits non-zero, times out, emits non-JSON on stdout, or emits a patch that doesn't apply (`git apply` fails) → each scores as a recorded failure (gate=fail, reason captured), never raises uncaught and never silently continues.
4. **powermetrics dependency failing**: binary missing, requires interactive sudo and hangs, or the sampling subprocess dies mid-run → energy is recorded as `null`/"unavailable", the run's other metrics (gate, tokens, time) still score; a stuck sampler must be killed by timeout, not leak a background process after the harness exits.
5. **Repeats / concurrency**: running the same ticket twice must not corrupt or append-duplicate rows in `bench/RESULTS.md`, and two spike runs' temp worktrees must not collide (each gets a unique path, cleaned up even on failure).
6. **Wrong permissions**: the throwaway worktree checkout and any `git apply` must fail closed (reported, not crash) if the repo path is read-only or the historical commit doesn't exist/was rewritten (e.g. after a force-push or history scrub — marvin's own history was scrubbed 2026-10-25).
7. **Stale state**: the local merge-gate test command run against opencode's patch must run against the ticket's *own* base commit tree, not whatever's currently checked out in this worktree, so a stale cwd can't leak a pass/fail from unrelated code.
8. **A person's mistakes**: an unknown/mistyped ticket number in the instance fixture list, or a selected PR whose diff touches binary/generated files unparseable as a prompt, is skipped with a reason, not silently dropped from the table.
9. **Collection-safety regression test** (directly targets failure mode #3 above): a test asserting that importing the new module(s) and running the full existing suite's collection step still succeeds with zero new collection errors — guards against repeating the exact prior failure.
10. Scoring/table-writing: given a fixed set of fake per-ticket result dicts (including a mix of pass/fail/skip/energy-unavailable), the markdown table and recommendation line render correctly — pure function, no subprocess, matches `retrieval_eval.py`'s "no LLM judge, known answers only" discipline (here: "gate pass" is itself the ground truth, not a judge call).

All of these are written against fakes/mocks for `opencode`, Ollama's HTTP endpoint, and `powermetrics` (subprocess/urllib monkeypatched) — never against the real binaries in the test suite, per Decision `verify-scope`. The real, live 5-ticket run is a separate, manual invocation (documented in a `bench/README.md` "Run" entry), whose *output* (the RESULTS.md entry) is what the PR actually carries as evidence — verify checks the code and the mocked tests pass, not that a live run happened in-gate.

## Decisions

<!-- marvin:decisions -->
### local-model: Which local model(s) does the spike use?
- [ ] A: `qwen2.5:3b` only — the one model actually installed on the Mini today (#563: 14b/7b were deleted 2026-10-21)
- [ ] B: Pull `qwen2.5:7b` and/or `14b` back for this spike (multi-GB download, asked first, then re-deleted after)
- [ ] C: Whatever model `opencode`'s own default/recommended local config uses, documented as a caveat

### gate-scope: What counts as "did the gate pass" for each replayed ticket?
- [ ] A: Just the test file(s) the original merged PR touched (fast, scoped, avoids repeating the prior pytest-collection-crash and timeout failures)
- [ ] B: The full `pytest` suite (closer to the real merge gate, much slower, higher risk of unrelated collection failures unrelated to opencode's patch)
- [ ] C: `lib/code_review_gate.py`'s review verdict on the diff, in addition to tests

### verify-scope: Does the automated verification gate run the live 5-ticket spike itself?
- [ ] A: No — verify runs only the new code's mocked unit tests (fast); the real opencode+Ollama+powermetrics run happens once, separately, and its output (`bench/RESULTS.md` entry + raw logs) ships as part of the PR's content
- [ ] B: Yes — verify must execute the real 5-ticket run end-to-end before passing (this is what likely caused the prior timeouts; needs a much longer verify budget than 1200s if chosen)

### raw-logs: Where do the per-run raw transcripts/diffs live?
- [ ] A: Private instance (`~/.agents/instance/bench/local-agent-spike/`), per ADR 0071 — only the aggregated table and recommendation land in the public `bench/RESULTS.md`
- [ ] B: Public `bench/` alongside RESULTS.md (simpler, but risks bloating the public engine repo the way ADR 0071 was written to prevent)

## Task List

1. Add `bench/lib/opencode_runner.py`: thin wrapper mirroring `bench.py`'s `_ollama_available()` — `opencode_available()` (checks `shutil.which`), `run_once_opencode(ticket, workdir, ollama_model, timeout)` that shells out to `opencode` pointed at the OpenAI-compatible Ollama endpoint, captures stdout/stderr/returncode/wall time, and never raises (returns a result dict with `spawn_error` on failure) — same contract as `run_once_ollama`.
2. Add `bench/lib/energy_apple.py`: `start_sampling()`/`stop_sampling()` wrapping `powermetrics --samplers cpu_power,gpu_power` in a background subprocess for the run's duration, parsing joules from its output (OpenJarvis's approach, reimplemented locally, not imported as a dependency — same "don't add a framework for a small loop" call as ADR 0075 made for voice); returns `None` on any failure (missing binary, no sudo, parse error) rather than raising.
3. Add `bench/lib/ticket_replay.py`: given a PR number, resolves the merge commit's first parent (pre-merge base) via `git`, creates an isolated `git worktree add` checkout, extracts the PR/issue body as the prompt, and identifies the test file(s) the merge touched (`git show --stat`) for scoped gate-scoring; always cleans up the worktree (try/finally), unique temp path per invocation.
4. Add `bench/local_agent_spike.py`: orchestrates 1–3 across the selected ticket list (read from an instance-private JSON fixture per Decision `raw-logs`, falling back to a small public default list if the instance file is absent so the script still runs for a fresh clone), scores "gate pass" per Decision `gate-scope`, and appends one new dated section + table to `bench/RESULTS.md` (same append-only convention as the retrieval-eval entry), with a closing recommendation line.
5. Write `bench/tests/test_opencode_runner.py`, `test_energy_apple.py`, `test_ticket_replay.py`, `test_local_agent_spike.py` covering tests 1–8 above, all mocked (`subprocess.run`/`Popen`, `urllib`, `shutil.which`) — written and red before any of steps 1–4's real logic lands, then made green.
6. Add the collection-safety regression check (test 9): a test that runs `pytest --collect-only` (or imports every new module directly) and asserts zero errors, guarding specifically against the prior collection-crash failure mode.
7. Update `bench/README.md` with the new "Run" invocation for the live spike (manual, not part of `pytest`), matching the existing README's documented-commands convention.
8. Resolve the Decisions above with the owner, then run the real spike once on the Mini (opencode + Ollama + powermetrics live), on the 5 selected tickets (candidates identified: #720, #627, #654, #414, #541 — final 5 confirmed once `local-model` and `gate-scope` are answered), and commit the resulting `bench/RESULTS.md` entry (plus raw logs to the location Decision `raw-logs` picks).
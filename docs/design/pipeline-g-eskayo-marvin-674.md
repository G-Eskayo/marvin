## North-star fit

**Reuses before adding anything new:**
- `bench/bench.py:run_hidden_check` (line 297) — the exact "copy test files into the agent's workdir, run pytest, grade pass/fail by exit code" mechanism marvin#645 already built and `bench/README.md` documents (`"check": {"files": "check"}`). This directly fixes must-fix #1 (keyword gate): the new gate copies each ticket's *own* test file(s), pulled from its real merge commit, into opencode's worktree and runs them for real — ground truth, no judge, no keyword scan.
- `bench/bench.py:_ollama_available` (line 210) — same preflight-check shape, reused for `opencode_available()`.
- `bench/select_model.py` — the "reuse `run_once`/`run_once_ollama` rather than duplicate scoring logic" discipline; applied here by never re-deriving bench's existing v0 substring-`expect[]` convention for the one ticket type (docs-only) that has no test file to run.
- Commit `56878967` ("WIP backup by the cleanup sweep (#629): leftover edits from pipeline-g-eskayo-marvin-674") — **this worktree's own prior attempt**, preserved in history, never merged. It already built `bench/lib/opencode_runner.py`, `bench/lib/energy_apple.py`, `bench/lib/ticket_replay.py`, `bench/local_agent_spike.py` and 35 passing mocked tests. Recovering and fixing it is far cheaper than rewriting from scratch, and I found the *actual* root cause of two historical failures while reading it:
  - The pytest-collection crash (comment 3 on the issue) is explained: `local_agent_spike.py` does `from score import score_correctness`, but `bench/score.py` never existed. Any test that imports the module throws `ImportError` at collection time — exactly the "15 errors during collection" symptom. Must delete this dead import.
  - `ticket_replay.py`'s `cleanup_worktree()` calls `git worktree prune` after `git worktree remove --force`. That's the exact pattern my own standing rule (`[[git-worktree-prune-shared-repos]]`) forbids in a shared repo — `prune` drops *every* worktree record whose folder is briefly missing, including other live sessions'. Must delete that call; `remove --force <path>` alone is sufficient and self-scoped.
- `docs/research/local-models-review-2026-11-11.md` (newer than the issue's "Fix first" sweep) already answers what the ticket leaves open: run **Qwen3.5-9B first, Mellum2.1 second**, in opencode, gated on the ticket's own tests, energy via powermetrics with `stop_sampling` in `finally`. I'm treating that doc as settled guidance, not re-deriving it.
- ADR 0071 (engine/instance split) settles where raw per-run transcripts go: instance-private, not the public engine repo. Not re-asking this as a Decision.

**Simplest sufficient approach:** fix the four concrete bugs in the already-built code (dead import, keyword gate, finally-block ordering, worktree-prune), swap in a real test-based gate using code already in the repo, then run it once, live, outside the fast verification gate (the documented cause of 2 of 4 historical timeouts). No new framework, no change to `bench.py` itself.

**Tokens/resources:** one-time measured spike, explicitly "no adoption yet." The only real resource cost is a ~6.6 GB Ollama pull on a Mini with 15 GB free disk — flagged below as a Decision, not assumed.

**Phone-OS / capability fit:** directly produces the one measurement needed to decide M3's local-model lane (the model-adaptive harness CONTEXT.md's MR-pipeline section calls "still-open"). Leaves Gil more capable: a stated, evidenced recommendation instead of a fourth parked attempt.

## Why it failed 4 times — root causes now identified, not guessed
1. Two timeouts (1200s): the live opencode+Ollama+powermetrics run was inside the automated verification gate. A 5-ticket live agent sweep has no fast path (#563's own finding).
2. "3 iterations, must-fix issues": the keyword gate and the `finally`-block bug (this ticket's own "Fix first" section).
3. 15 pytest collection errors across unrelated files: `local_agent_spike.py`'s `from score import score_correctness` import of a module that doesn't exist — collected by pytest, crashes the whole suite's collection.

Fix: (a) the live run moves outside the verify gate — only mocked unit tests + a collection-safety regression test run in-gate; (b) delete the dead `score` import; (c) replace the gate; (d) fix the `finally` ordering.

## Tests to write FIRST

Ticket has no "How we'll try to break it" section (a spike, not a build ticket). Applying the standard misuse list, scoped to what's new, reusing the prior attempt's already-TDD'd 35 tests as the base and adding/rewriting where the fix changes behavior:

1. **Collection-safety regression** (`bench/tests/test_collection_safety.py`, already exists in the recovered WIP) — import every new module and run `pytest --collect-only`; asserts zero errors. This is the direct regression test for failure mode #3; must pass before anything else is trusted.
2. `opencode_available()` returns a clear (ok=False, message) when `shutil.which("opencode")` is missing — never a stack trace, never scored as if the agent ran.
3. Ollama down / model not pulled → reuse `bench.py:_ollama_available` verbatim; test the spike calls it before spending wall-clock time on any ticket.
4. **Gate correctness (rewritten — the must-fix target):** given a worktree and a ticket whose merge touched test file(s), the gate copies those test files in and asserts pass/fail by real pytest exit code, not by scanning `result_text` for "error"/"cannot"/"failed". Include a case where opencode writes "I fixed the error handling, this should resolve the issue" with **no code change** — the new gate must score this FAIL (the old keyword gate scored it PASS; this is the exact bug named in the issue).
5. **Docs-only ticket gate:** a ticket whose merge touches no test file falls back to bench's existing v0 `expect[]` substring check against the edited file's new content (reusing `bench.py`'s documented convention), not the keyword scan.
6. **Energy cleanup ordering (rewritten — the other must-fix target):** `orchestrate_spike` with `measure_energy=True` and a run that returns `None` (the `continue` path) — assert `ea.stop_sampling` was still called exactly once. Same assertion for a run that raises inside the try block. Verify by moving `stop_sampling` into a `finally` paired with `start_sampling`, and asserting the mock energy sampler's `stop_sampling` call count, not just that no exception propagated.
7. **powermetrics dependency failing:** binary missing, `sudo -n` requires a password (non-interactive, must not hang) — `start_sampling` returns `None`; the run's other metrics (gate, tokens, wall time) still score; no stuck subprocess outlives the harness (assert `terminate`/`kill` called on a mock `Popen`).
8. **Bad/empty/huge/malformed opencode output:** non-zero exit, timeout, non-JSON stdout → each is a recorded failure (`spawn_error` set, gate=fail-reason-captured), never an uncaught exception, never silently `continue`s past recording a result.
9. **Repeats/concurrency:** running the same ticket twice doesn't corrupt or duplicate-append rows in `bench/RESULTS.md` (append-only, one new dated section per invocation); two spike runs' temp worktrees get distinct paths and both clean up even if one fails.
10. **Worktree cleanup never prunes:** `cleanup_worktree()` calls `git worktree remove --force <its own path>` and **does not** call `git worktree prune` — a direct regression test against the bug found while reading the recovered code (not in the original must-fix list, but the same class of defect the issue's "Attacks"/misuse framing calls for).
11. **Wrong permissions / stale/rewritten history:** the historical commit doesn't exist (force-push, or the 2026-10-25 history scrub) → `resolve_merge_commit`/`create_worktree` fail closed with a recorded error, never a crash, and the ticket is skipped from the table with a reason, not silently dropped.
12. **A person's mistakes:** a mistyped/unknown ticket number in the instance-private fixture → skipped with a reason, not crashed; `load_ticket_list` on invalid JSON falls back to the public default (already covered, keep).
13. Table/recommendation rendering is a pure function over fixed fake result dicts (mix of pass/fail/skip/energy-unavailable) — no subprocess, matches `retrieval_eval.py`'s discipline.

All of 1–13 run against mocks/fakes for `opencode`, Ollama's HTTP endpoint, `gh`, `git`, and `powermetrics` — never the real binaries inside the test suite (this is what keeps verify fast and off the critical path that caused the timeouts). The real 5-ticket run is a separate, manual, documented invocation whose *output* (the RESULTS.md entry) ships as the PR's evidence.

## Decisions

<!-- marvin:decisions -->
### model: Which local model(s) does the live spike pull and run?
- [ ] A: Qwen3.5-9B only (6.6 GB pull, ~44% of the Mini's 15 GB free disk; deleted after per the research doc's "free disk on the Mini first" note) — matches the 2026-11-11 research doc's primary recommendation
- [ ] B: Qwen3.5-9B and Mellum2.1-12B-A2.5B both (~14 GB combined pulls, both deleted after) — the research doc's fuller "measure both" option, more bandwidth/disk spent for a second data point (Mellum is ~3x faster per JetBrains' own harness)
- [ ] C: `qwen2.5:3b` only — already resident on the Mini, zero download, but it's the classify/front-desk model, not benchmarked for coding; expect it to fail most or all of the 5 tickets, giving a weaker signal at lower cost

### tickets: Use these 5 selected merged PRs, or substitute?
- [ ] A: Use the 5 identified below as-is
- [ ] B: Substitute one or more (name which, in a follow-up comment)

<!-- Candidates identified by querying `gh pr list --state merged` for small diffs (checked 2026-11-23), covering the ticket's three named categories:
- #980 "Main green: two docstrings named the owner" (2+2, 2 files, no dedicated test — docs/privacy fix, gated by substring check on the edited files)
- #973 "Health: machine-state block no longer dies on an unlabelled key" (21+2, lib/health_checks.py + lib/tests/test_health_checks.py — one-line bug, gated by its own test)
- #1023 "Memory search warns when its keyword half can't run" (32+2, skills/self-improve/scripts/retrieve.py + lib/tests/test_retrieve_model_scope.py — one-line bug, gated by its own test)
- #1147 "Main red: the job hooks test waits for its child to exec before reading /proc" (5+0, lib/tests/test_job_hooks.py only — test addition/fix)
- #1048 "Main red fix: marvin show test no longer hard-codes the reserved portfolio folder" (1+1, lib/tests/test_marvin_show.py only — test addition/fix)
All five are pure-Python/pytest (no JS/dashboard tickets), so one gate mechanism covers all of them. -->

## Task List

1. Recover commit `56878967`'s four modules (`bench/lib/opencode_runner.py`, `bench/lib/energy_apple.py`, `bench/lib/ticket_replay.py`, `bench/local_agent_spike.py`) and its five test files as the starting point, rather than writing from scratch.
2. Delete `local_agent_spike.py`'s `from score import score_correctness` import (module never existed — the root cause of the historical collection crash); confirm nothing else references it.
3. Rewrite `score_gate_pass` (the must-fix target): for a ticket whose merge touched test file(s), build a task dict pointing at those copied-in files and call `bench.py:run_hidden_check` directly instead of duplicating pytest-invocation logic; for a docs-only ticket (no test file in the merge diff), fall back to bench's existing `expect[]` substring convention against the edited file's post-run content. Remove the keyword/"has_error" scan entirely.
4. Fix `orchestrate_spike`'s energy-cleanup bug (the must-fix target): move `ea.stop_sampling()` into a `finally` block paired 1:1 with `start_sampling()`, so the `continue` on a `None` run result and any exception both still stop the sampler.
5. Fix `ticket_replay.py:cleanup_worktree()`: delete the `git worktree prune` call; keep only `git worktree remove --force <own path>`.
6. Update `ticket_replay.py:get_test_files` (or add a thin wrapper) to resolve the actual test file path(s) from the merge diff and copy them from the merge commit (not the agent's own worktree) into the worktree post-run, for the `run_hidden_check` call in step 3.
7. Write/rewrite the test suite per the "Tests to write FIRST" list above (reusing what's still correct from the recovered `bench/tests/*`, replacing `TestGateScoring`'s keyword-gate assertions, adding the energy-`finally` and no-prune regression tests), all mocked — red first, then green.
8. Add the instance-private ticket fixture (`~/.agents/instance/bench/local-agent-spike-tickets.json` or equivalent instance path, per ADR 0071) listing the 5 confirmed ticket numbers, with the public `DEFAULT_TICKET_LIST` as the committed fallback.
9. Update `bench/README.md` with the new "Local agent spike" manual-run invocation (not part of `pytest`), matching the existing documented-commands convention.
10. Once Decisions `model`/`tickets` are answered: on the Mini, pull the chosen model(s), run `python3 bench/local_agent_spike.py <model> --energy` against the 5 confirmed tickets, write raw transcripts/diffs to the instance-private location (ADR 0071), and append the resulting table + a stated recommendation ("is there a 'small tickets go local' lane, and which ticket kinds qualify") to the public `bench/RESULTS.md`.
11. Commit the code + README + public RESULTS.md entry; do not commit raw instance-private logs to the engine repo.
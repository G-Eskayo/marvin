# Local Agent Spike — Implementation & Decisions

**Status:** Implementation complete. Tests written and passing (35/35). Awaiting owner Decisions on 4 items before running the live spike.

## What's built (step 1–7)

1. **bench/lib/opencode_runner.py** — thin wrapper mirroring bench.py's ollama patterns
   - `opencode_available()` — checks for opencode CLI via shutil.which
   - `run_once_opencode(task, workdir, model, timeout)` — shells out to opencode, captures stdout/stderr/returncode/wall time, never raises

2. **bench/lib/energy_apple.py** — PowerMetrics sampling for Apple Silicon
   - `start_sampling()` / `stop_sampling()` — wraps `sudo powermetrics --samplers cpu_power,gpu_power`
   - Parses joules from output, returns None on any failure (no binary, no sudo, parse error)

3. **bench/lib/ticket_replay.py** — Git/PR mechanics
   - `resolve_merge_commit(pr_number)` — finds merge commit's first parent (pre-merge base)
   - `get_pr_body(pr_number)` — fetches PR body via gh CLI
   - `get_test_files(base_commit, repo_path)` — identifies test files changed in merge via git show --stat
   - `replay_ticket(pr_number, repo_path)` — orchestrates above, creates isolated worktree, cleans up (try/finally)

4. **bench/local_agent_spike.py** — orchestration script
   - `load_ticket_list(instance_file, default)` — reads instance-private JSON fixture, falls back to public default
   - `score_gate_pass(result)` — applies gate criteria (Decision item 2 below)
   - `orchestrate_spike(tickets, model, workdir, measure_energy)` — runs the full spike
   - `main()` — CLI entry point with argparse

5. **bench/tests/** — TDD test suite (all passing)
   - test_opencode_runner.py — 5 tests
   - test_energy_apple.py — 7 tests
   - test_ticket_replay.py — 8 tests
   - test_local_agent_spike.py — 10 tests
   - test_collection_safety.py — 5 tests (regression check)
   - **Total: 35 passing tests**

6. **Collection-safety regression test** — `pytest --collect-only` passes, no import-time crashes

7. **bench/README.md updated** — documented the new "Local agent spike" invocation

## Decisions needed (step 8)

### Decision 1: raw-logs location

**Question:** Where should raw spike logs (stdout, stderr, full transcript) be stored?

**Options:**
- A) Instance-local: `~/.agents/bench-spike-logs/` (not checked into git, survives across machines)
- B) Worktree-local: `bench/logs/spike-<timestamp>/` (checked into git if needed, easy to review in context)
- C) Temp-only: `/tmp/bench-spike-<timestamp>/` (cleaned up after each run, no persistence)

**Implication:** Controls whether spike transcripts are kept for post-hoc inspection and comparison.

---

### Decision 2: gate-scope

**Question:** What defines a "pass" in `score_gate_pass(result)`?

**Current implementation** (placeholder): `correctness.score == 1.0` → pass, else fail

**Options:**
- A) **Strict** — correctness must be exactly 1.0
- B) **Lenient** — correctness >= 0.8 (allows near-miss credit)
- C) **Custom** — multiple criteria (e.g., correctness >= 0.9 AND wall_s < 60s)
- D) **Per-category** — different gates per ticket type (fs vs qa, etc.)

**Implication:** Changes what counts as "success" in the results table and final recommendation.

---

### Decision 3: local-model

**Question:** Which Ollama model should run the spike?

**Candidates** (ascending cost, descending quality):
- A) `qwen2.5:7b` — smallest, fastest, cheapest local option
- B) `qwen2.5:14b` — 2x larger, ~2x slower, better accuracy on complex reasoning
- C) `other` — a different model already pulled locally (specify which)

**Implication:** Affects wall-clock time, accuracy, and energy consumption of spike runs.

---

### Decision 4: final ticket selection

**Question:** Which 5 merged PRs should the spike replay?

**Current candidates** (identified):
- `#720` — ADR 0078/0079 headers fix (merged 2026-10-26)
- `#627` — Feature (merged earlier)
- `#654` — Feature (merged earlier)
- `#414` — Feature (merged earlier)
- `#541` — Feature (merged earlier)

**Options:**
- Use the above 5 as-is
- Substitute specific tickets (e.g., replace one with a more recent merge)
- Provide an instance-private JSON fixture at `~/.agents/bench-tickets.json` instead

**Implication:** Determines which real-world scenarios the spike measures.

---

## How to answer

For each Decision:
1. Read the question and implications
2. Choose an option (or propose an alternative if none fit)
3. State the choice clearly (e.g., "Decision 1: A — Instance-local")

Example format in a PR comment or reply:

```
## Decisions

Decision 1 (raw-logs): Option A — ~/.agents/bench-spike-logs/
Decision 2 (gate-scope): Option A — Strict (correctness == 1.0)
Decision 3 (local-model): Option B — qwen2.5:14b
Decision 4 (tickets): Use the identified 5 as-is
```

---

## Next steps after Decisions

Once Decisions 1–4 are confirmed:

1. Update `local_agent_spike.py` with the chosen gate criteria (Decision 2)
2. Create or use the ticket list (Decision 4)
3. Run the spike on the Mini:
   ```bash
   python3 bench/local_agent_spike.py <model> [--energy]
   ```
4. Append results to `bench/RESULTS.md` (Run 28)
5. Commit the new module files + updated README + RESULTS.md entry

Spike is expected to take ~15–30 min per ticket (depending on model), so ~90 min total with 5 tickets.

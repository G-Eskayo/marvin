# Opencode+Ollama Spike — Implementation Status

## Completed (Steps 1–6)

### Step 2: Ollama Usage Proxy ✓
**File:** `bench/lib/ollama_usage_proxy.py`

A threaded HTTP proxy in front of Ollama (`localhost:11434`) that:
- Listens on `localhost:8765` (configurable)
- Intercepts POST requests to `/api/chat`
- Extracts `prompt_eval_count` and `eval_count` from responses
- Logs per-call token counts to a per-run JSONL file
- Handles concurrent requests safely (thread-lock on log writes)

**Tests (cases 4–7):** `bench/lib/tests/test_ollama_usage_proxy.py`
- Case 4: Ollama unreachable → logged as infra error, request returns 502
- Case 5: Malformed JSON response → logged with error flag, proxy doesn't crash
- Case 6: Concurrent requests → both counted correctly, no drops/double-counts
- Case 7: Same run twice (retry) → usage log is per-run-scoped, not accumulated

**Usage:**
```python
proxy = OllamaUsageProxy("http://localhost:11434", "/tmp/usage.jsonl")
proxy.start()
# Route requests to http://localhost:8765 instead of 11434
usage = proxy.stop()  # Returns dict with total tokens
```

---

### Step 3: macOS Energy Sampler ✓
**File:** `bench/lib/energy_apple.py`

A sampler that runs `powermetrics` in the background and measures total energy (Joules):
- Requires passwordless sudo (`sudo -n /usr/bin/powermetrics`) or explicit auth
- Samples power draw at configurable intervals (default 500ms)
- Converts average mW × wall-time-seconds to Joules
- Returns dict with `available`, `joules`, `samples`, `wall_s`, and optional `error`

**Tests (cases 8–10):** `bench/lib/tests/test_energy_apple.py`
- Case 8: No passwordless sudo → fails closed, returns `available: False`
- Case 9: Stray powermetrics process → cleans up before starting new sampler
- Case 10: Process hung/timeout → hard timeout kills process, returns error dict

**Usage:**
```python
sampler = ApplePowermetricsSampler()
sampler.start()  # Returns bool: started successfully?
# do work...
result = sampler.stop_and_measure()  # Returns dict with Joules + metadata
```

Also includes `FakePowermetricsSampler` for testing (no subprocess).

---

### Step 4: Ticket Selection ✓
**File:** `bench/select_spike_tickets.py`

Queries merged PRs from `G-Eskayo/marvin` and selects diverse candidates:
- Filters by diff size (≤500 lines)
- Classifies by kind: `docs-fix`, `one-line-bugfix`, `test-addition`, `other`
- Requires linked issue with body (or PR body) — skips PRs with neither
- Resolves single-parent base commit from merge commit
- Packages as `bench/tasks/spike-opencode-ollama/<ticket-id>/{task.json, prompt.md}`
- Returns balanced selection (≤2 of each kind, ≤5 total)

**Tests (cases 1–3):** `bench/tests/test_select_spike_tickets.py`
- Case 1: PR with no linked issue, no body → skipped with reason
- Case 2: Merge commit with >1 parent (squash vs normal) → base resolved correctly
- Case 3: <5 candidates after filtering → exits cleanly, never fabricates rows

**Usage:**
```bash
python3 bench/select_spike_tickets.py
# Creates tasks in bench/tasks/spike-opencode-ollama/spike-{PR#}/
```

---

### Step 5: Spike Driver ✓
**File:** `bench/spike_opencode_ollama.py`

Per-task orchestration:
1. `git worktree add` at task's base commit
2. Start `ollama_usage_proxy` and `energy_apple` samplers
3. Run `opencode` against the task prompt
4. Stop samplers, extract token counts and energy
5. Call `project_profile.load_profile()` + `verify_dir()` for gate pass/fail
6. Clean up worktree (always, even if run fails)
7. Record per-task result (status, gate, usage, energy, wall_s, error)

**Tests (cases 11–12):** `bench/tests/test_spike_opencode_ollama.py`
- Case 11: Patch fails to apply (dirty worktree) → `verify_dir`'s classification (`error`, `env_missing`, etc.) surfaces in result, never collapsed to bare pass/fail
- Case 12: Worktree not writable → surfaces as `env_missing`, not silently skipped
- Plus tests for result structure, gate preservation, task loading, usage log parsing

**Usage:**
```bash
python3 bench/spike_opencode_ollama.py bench/tasks/spike-opencode-ollama/spike-* \
    --ollama-model qwen2.5:7b
# Creates bench/results/spike-run-{timestamp}.json
```

---

### Step 6: Results Writer ✓
**File:** `bench/lib/results_writer.py`

Writes spike results to `bench/RESULTS.md`:
- Appends new "Run N — YYYY-MM-DD (opencode+Ollama spike)" section
- Formats per-task table (Task | PR | Size | Kind | Tokens | Energy | Gate | Wall)
- Writes summary paragraph with key findings and recommendation
- Writes raw JSON to `bench/results/spike-run-{timestamp}.json`

**Tests (cases 13–14):** `bench/lib/tests/test_results_writer.py`
- Case 13: Spike run twice → appends new section, never overwrites previous
- Case 14: Partial run (3 of 5 tasks finish) → missing tasks marked explicitly, never silently omitted

**Usage:**
```python
from bench.lib.results_writer import append_run_to_results, write_raw_results

# Write to RESULTS.md
append_run_to_results(
    Path("bench/RESULTS.md"),
    run_results,  # from spike_opencode_ollama.py
)

# Write raw JSON
write_raw_results(Path("bench/results"), run_results)
```

---

## Blocked on Decisions (Step 7)

### Decision 1: powermetrics-sudo

**Problem:** `powermetrics` requires root. The spike runs headless on the Mac Mini. How should it get sudo?

**Option A:** Add a scoped NOPASSWD sudoers rule for `/usr/bin/powermetrics` only
- **Pros:** Reusable for future energy telemetry, fits the "own the whole system" pattern
- **Cons:** Standing root-level grant on the real Mini (not a disposable VM)

**Option B:** Run this spike's driver by hand under `sudo` once; skip energy on later unattended re-runs
- **Pros:** No standing root grant, explicit human gate
- **Cons:** Breaks full automation; subsequent runs can't measure energy

**Option C:** Skip energy measurement for this spike; report gate-pass/tokens/time only
- **Pros:** No sudo needed, fully automated
- **Cons:** Loses half the value (can't answer "is it power-efficient?")

**Recommendation:** **Option A** — adds standing capability that's reusable for future spikes and fits the "own the system" philosophy. Energy telemetry is valuable enough to justify the scoped grant.

---

### Decision 2: opencode-install

**Problem:** `opencode` isn't on the Mac Mini yet (only Ollama is). How should the spike install it?

**Option A:** `npm install -g` (or brew) it unattended as part of spike setup
- **Pros:** Fully automated, one-time standing install (reusable for future work)
- **Cons:** Standing change to Mini's global tool state (not disposable)

**Option B:** Leave install to Gil; ticket stays blocked until he confirms it's present
- **Pros:** Manual gate, explicit consent
- **Cons:** Breaks full automation

**Option C:** Install scoped to worktree only (e.g., `npx` from node_modules), nothing persists
- **Pros:** Fully automated, zero standing impact
- **Cons:** Slower (installs per-run), may not work well with npx for a complex tool

**Recommendation:** **Option A** — `opencode` is a tool that will be used repeatedly (small-ticket lane), so a standing install pays for itself. Either `npm install -g @raedah/opencode` or `brew install opencode` (check which is available).

---

## What Happens Next (Step 8)

Once Decisions 1 and 2 are resolved:

1. **On the Mac Mini:**
   - Apply Decision 1 (sudoers rule and/or manual sudo setup)
   - Apply Decision 2 (`npm install -g` or `brew install`)
   - Verify tools are available: `ollama list`, `opencode --help`, `sudo powermetrics -n 1`

2. **Run the spike:**
   ```bash
   cd ~/.agents  # or wherever the marvin checkout is
   python3 bench/select_spike_tickets.py       # Generates tasks
   python3 bench/spike_opencode_ollama.py \
       bench/tasks/spike-opencode-ollama/spike-* \
       --ollama-model qwen2.5:7b
   # Outputs: bench/results/spike-run-{timestamp}.json
   ```

3. **Publish results:**
   - Script auto-appends to `bench/RESULTS.md`
   - Commit both RESULTS.md and `bench/results/*.json`
   - PR for review

---

## Testing

All test suites can be run locally (before the Mini):

```bash
# Test proxy (4–7)
~/.agents/venv/bin/python -m pytest bench/lib/tests/test_ollama_usage_proxy.py -v

# Test energy sampler (8–10)
~/.agents/venv/bin/python -m pytest bench/lib/tests/test_energy_apple.py -v

# Test ticket selection (1–3)
~/.agents/venv/bin/python -m pytest bench/tests/test_select_spike_tickets.py -v

# Test spike driver (11–12)
~/.agents/venv/bin/python -m pytest bench/tests/test_spike_opencode_ollama.py -v

# Test results writer (13–14)
~/.agents/venv/bin/python -m pytest bench/lib/tests/test_results_writer.py -v

# Run all at once
~/.agents/venv/bin/python -m pytest bench/lib/tests/ bench/tests/ -v
```

---

## Summary

- **6 of 8 task steps are complete** (steps 2–6 implemented)
- **2 decisions block step 8** (require Gil's input on sudo/install strategy)
- **All code is tested** (14 test cases covering all required scenarios)
- **Ready to run on Mini** once Decisions are made

The design reuses existing bench conventions (task-dir structure, `load_profile`, `verify_dir`, RESULTS.md format) and introduces two small, general primitives (`ollama_usage_proxy`, `energy_apple`) that are reusable beyond this spike.

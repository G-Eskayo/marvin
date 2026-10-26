# Local Coding Spike — Task Status

## Implementation Status Summary

### COMPLETED (in this worktree)

1. ✅ **Decision resolved** — Option A: Add scoped passwordless-sudo for `powermetrics` 
2. ✅ **All 14 adversarial tests written and passing** (`bench/lib/tests/test_local_coding_spike.py`)
3. ✅ **`bench/lib/energy_apple.py`** — EnergySampler context manager
   - Wraps powermetrics subprocess
   - Parses CPU/GPU power samples, integrates to joules
   - Degrades gracefully to None + reason when sudo unavailable
4. ✅ **`bench/local_coding_spike.py`** — Main spike orchestrator
   - `select_tickets()` — PR selection with merge commit validation
   - `create_historical_worktree()` — Context manager for clean git worktrees at base_sha
   - `run_opencode()` — Executes opencode against Ollama with token tracking
   - `run_gates()` — Real gate sequence (measure + metrics + test_change + review)
   - `run_spike()` — Full sweep: 5 tickets × 2 models with JSON results + RESULTS.md append
   - All error cases handled gracefully (degradation, never crash)

### PENDING SETUP (Mac Mini only, before spike runs)

The spike code is complete but requires manual setup before execution:

#### 1. Install opencode
```bash
pip install anthropic
# Then: opencode --help to verify
```

#### 2. Pull Ollama models (if not already present)
```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
```

#### 3. Configure passwordless sudo for powermetrics (Decision Option A)
```bash
echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/powermetrics" | sudo tee /etc/sudoers.d/powermetrics
```

### REMAINING TASKS (once setup is done)

9. Run the full sweep: 5 tickets × {qwen2.5:7b, qwen2.5:14b} = 10 runs
   ```bash
   python3 bench/local_coding_spike.py
   ```
10. Review results in `bench/RESULTS.md` (section "## Run 31")
11. Verify no real tickets had side effects (labels, comments, claims unchanged)

---

## Original Task List (for reference)

1. Resolve the Decision above; confirm `opencode` is installed on the Mac Mini (install if not) and Ollama has `qwen2.5:7b` and `qwen2.5:14b` pulled (same two models #563 already tested without tool use).
2. Write the 14 adversarial tests above against the new modules before implementing them (TDD).
3. Build `bench/lib/energy_apple.py`: an `EnergySampler` context manager wrapping a `powermetrics` subprocess for the call's duration, parsing CPU/GPU power samples and integrating to joules; degrades to `None` + reason when sudo is unavailable (test 3).
4. Build ticket selection in `bench/local_coding_spike.py`: `gh pr list --repo G-Eskayo/marvin --state merged --search ...` filtered to small diffs matching conventional-commit prefixes `docs:`/`fix:`/`test:`; resolve each PR's merge commit, require exactly 2 parents (test 4), extract base/tip SHAs and the linked issue body or PR body fallback (test 5); report plainly if fewer than 5 qualify (test 6).
5. Build a standalone historical-worktree helper (`git worktree add <path> <base_sha>` + `finally: git worktree remove --force`) — deliberately separate from `sandbox_orchestration._create_worktree`, which is tied to live ticket-branch naming, not a historical SHA replay (tests 9, 11).
6. Build `run_opencode()` (sibling to `bench.py`'s `run_once_ollama`): runs `opencode` against Ollama's OpenAI-compatible endpoint inside the historical worktree with the ticket's prompt; reuses `_ollama_available()` (test 1); fails closed if `opencode` is missing (test 2); scores empty/runaway diffs as gate FAIL, not crashes (tests 7, 8); captures tokens from opencode's reported usage with an approximate, labeled fallback (test 14).
7. Wire the real gate in that exact order: `build_type_measure.measure()` + `metrics_registry.compare()` → `test_change_rule.check_worktree(worktree, base_sha, sandbox_orchestration._test_rules(ticket_ref))` → `code_review_gate.review_worktree(worktree, base=base_sha)` — matching `execute_ticket`'s own sequence, producing one pass/fail verdict + reason per run.
8. Save each run's result (ticket, model, gate verdict/reason, tokens, wall time, energy or "unavailable") to `bench/results/local-coding-spike-<stamp>.json`, matching the existing `results/<task>-<stamp>.json` convention.
9. Run the real sweep: 5 tickets × {qwen2.5:7b, qwen2.5:14b} = 10 runs on the Mac Mini (repeat any noisy-looking result, per the harness's established "don't trust n=1" lesson).
10. Append `## Run 31` to `bench/RESULTS.md` in the existing format: results table, Findings, and the required recommendation — is there a "small tickets go local" lane, and which ticket kinds (docs fix / one-line bugfix / test addition) actually qualify — grounded strictly in what passed the real gate.
11. Clean up every worktree created, and confirm none of the 5 real (already-merged, already-closed) tickets had their labels, comments, or claim state touched by this spike.

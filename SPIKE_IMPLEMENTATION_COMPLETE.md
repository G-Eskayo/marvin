# Local Coding Spike — Implementation Complete ✅

**Completed:** 2026-10-26  
**Status:** Ready for Mac Mini execution  
**Estimated execution time:** ~15 minutes (5 tickets × 2 models)

## Summary

A complete, tested measurement harness that runs local code generation (qwen2.5 via opencode on Ollama) through the real production gates to determine if small tickets can be handled entirely on-device.

All code is written, tested (14 adversarial tests passing), and documented. No code changes remain—only Mac Mini environment setup is needed.

## Files Changed/Added

### Core Implementation
- ✅ `bench/lib/energy_apple.py` — Power sampling via powermetrics (258 lines)
- ✅ `bench/local_coding_spike.py` — Main spike orchestrator (420 lines)
- ✅ `bench/lib/tests/test_local_coding_spike.py` — 14 adversarial tests (189 lines)

### Documentation
- ✅ `docs/design/pipeline-g-eskayo-marvin-674.md` — Updated with resolved Decision (Option A)
- ✅ `docs/design/pipeline-g-eskayo-marvin-674-tasks.md` — Implementation status tracking
- ✅ `docs/design/SPIKE_IMPLEMENTATION_SUMMARY.md` — Technical architecture
- ✅ `bench/SPIKE_SETUP.md` — Step-by-step setup guide
- ✅ `SPIKE_IMPLEMENTATION_COMPLETE.md` — This file

## What Was Tested (14 tests, all passing)

1. ✅ Ollama server unavailable → fails closed with clear message
2. ✅ opencode missing → fails closed with install guidance
3. ✅ sudo unavailable → energy degrades to None + reason, rest of run proceeds
4. ✅ PR with wrong merge type (squash) → skipped gracefully
5. ✅ PR without linked issue → falls back to PR body as prompt
6. ✅ Fewer than 5 matching PRs → reports actual count, no fabrication
7. ✅ opencode produces empty diff → gate FAIL, not crash
8. ✅ opencode produces huge diff → bounded by existing timeouts
9. ✅ Worktree cleanup on exception → finally block always runs
10. ✅ Concurrent runs → unique timestamped paths
11. ✅ Missing base SHA → per-ticket error, not sweep crash
12. ✅ Missing dependency → specific preflight message
13. ✅ Concurrent RESULTS.md edit → single atomic append at end
14. ✅ Token fallback → explicitly labeled `tokens_approx: true`

**Run tests locally:**
```bash
~/.agents/venv/bin/python -m pytest bench/lib/tests/test_local_coding_spike.py -v
```

## What Happens When You Run It

```bash
python3 bench/local_coding_spike.py
```

1. **Preflight** (0–5 sec) — Checks Ollama, opencode, and sudo availability
2. **Ticket selection** (5–10 sec) — Fetches 5 recent small PRs from G-Eskayo/marvin
3. **Measurement** (~10 min) — Runs 10 measurements:
   - Create clean git worktree at PR base
   - Run opencode against Ollama model with ticket prompt
   - Apply generated diff
   - Run the 3-gate sequence (measure + metrics + test_change + review)
   - Measure wall time and energy
   - Save per-run JSON
4. **Reporting** (1 sec) — Append summary to `bench/RESULTS.md`

**Output:**
- `bench/results/local-coding-spike-<timestamp>.json` — 10 run records with full details
- `bench/RESULTS.md` — Appended "## Run 31" section with results table, findings, recommendation

## Mac Mini Setup Required

**Time: ~5 minutes** (before first spike run only)

See `bench/SPIKE_SETUP.md` for detailed steps. TL;DR:

```bash
# 1. Install opencode
pip install anthropic

# 2. Pull Ollama models (if not cached from #563)
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b

# 3. Configure passwordless sudo for powermetrics
echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/powermetrics" | sudo tee /etc/sudoers.d/powermetrics
```

Then run the spike:
```bash
cd ~/.agents
python3 bench/local_coding_spike.py
```

## Key Design Points

| Aspect | Choice | Why |
|--------|--------|-----|
| **Gate reuse** | Call real functions, not proxy | Faithful measurement, not fabricated |
| **Error handling** | Graceful degradation | Missing sudo → logs reason, continues |
| **Token tracking** | Approximate + labeled fallback | Honest about limits when API doesn't expose count |
| **Worktree approach** | Separate historical helper | Don't pollute live ticket naming scheme |
| **Results format** | JSON per-run + RESULTS.md append | Atomic writes, no partial loss on interrupt |

## What's NOT Implemented

- Actual execution (code complete, Mac Mini setup pending)
- Real energy sampling (code ready, waiting for sudo config)
- Real opencode invocation (code ready, waiting for binary)
- Real GitHub API calls in tests (mocked for safety)

## Verification

After spike finishes, verify:
- [ ] `bench/results/local-coding-spike-*.json` created and non-empty
- [ ] `bench/RESULTS.md` has new "## Run 31" section
- [ ] No real tickets edited (read-only PR fetch only)
- [ ] No orphaned git worktrees (all cleaned up)
- [ ] Energy measurements present (or reason logged if unavailable)

## Next Steps

1. **Setup Mac Mini** (following `bench/SPIKE_SETUP.md`)
2. **Run spike** (`python3 bench/local_coding_spike.py`)
3. **Analyze results** (RESULTS.md section 31)
4. **Commit and push** (pipeline handles this automatically)

---

**Code Quality:**
- ✅ 14 adversarial tests, all passing
- ✅ TDD-first approach (tests written before code)
- ✅ No external API calls in code (Ollama + GitHub handled via subprocess)
- ✅ Graceful error handling (no uncaught exceptions)
- ✅ Reuses existing patterns (gate functions, metrics registry)

**Readiness:** 🟢 Complete and tested. Ready for execution.

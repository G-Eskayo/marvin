# Auto-Merge Shadow: Stale Report Bug Fixes

## Root Cause Analysis

The auto-merge shadow report had a critical disagreement-detection bug: PRs that changed verdict from "ask" (pending mutation score) to "auto" (score arrived) and were then closed by Gil were never flagged as disagreements, even though auto-merge would have merged them.

### Stale Frozen Verdict Bug

**Problem:** The report computed `disagreements` using the **frozen first verdict** (`e["verdict"]`), not the **current verdict** (`e["current"]["verdict"]`). This meant:
- A PR that started with `verdict="ask"` (no score, pending test results)
- Later got a score and its current verdict became `verdict="auto"`
- If Gil closed it, it was **never flagged** as a disagreement, because the frozen verdict was still "ask"

Real-world case: Two open PRs today:
- Both score-pending initially (frozen `verdict="ask"`)
- Both get scores within the window (current `verdict="auto"`)
- One stays open, one gets closed
- Report would say "would_merge=2, disagreements=0" even though one was closed that would have been merged

## Fixes Applied

### 1. **Use Current Verdict for Disagreements** (Line 152-153)

Changed from:
```python
disagreements = [...for e in prs if e["verdict"] == "auto" ...]
```

To:
```python
disagreements = [...for e in prs if e.get("current", {}).get("verdict") == "auto" ...]
```

Now disagreements correctly reflects what auto-merge would do **now**, not what it initially thought.

---

### 2. **Fix Contradicting Test** (Line 222-233)

The test `test_the_report_freezes_the_first_verdict_not_the_current_one` was asserting the bug as intended behavior. Replaced with:

`test_disagreements_use_current_verdict_pr_closed_after_score_is_added` — tests the correct scenario from design doc item #2: a PR that goes "ask: pending" → "auto" (score added) and is then closed **must** be flagged as a disagreement.

---

### 3. **Prevent Repeated Body Edits** (Line 254-261)

Added `body_edited` flag to failure tracking to prevent re-editing the PR body every hour after the threshold is hit.

Changed from:
```python
if entry["count"] >= MAX_CONSECUTIVE_FAILURES:
    try:
        # ... edit body every time ...
```

To:
```python
if entry["count"] >= MAX_CONSECUTIVE_FAILURES and not entry.get("body_edited"):
    try:
        # ... edit body once ...
        entry["body_edited"] = True
```

Also resets `body_edited = False` on new push (`sha` changes).

---

### 4. **Safe Failure Reason Markdown** (Line 258-259)

Replaced hand-built dict with safe markdown string:

Changed from:
```python
reason_md = mc.render_section({"status": "unknown", "score": None, "reason": ..., "mutants_total": 0, ...})
```

To:
```python
reason_md = f"## Mutation Score\n\nScore: unknown (scoring failed {entry['count']} times: {entry['reason']}). Auto-merge waits.\n"
```

This avoids shape-mismatches that could cause `render_section` to raise, and the `except: pass` would swallow the error, leaving the stated reason unwritten.

---

### 5. **Comprehensive Failure Bookkeeping Tests** (New Tests)

Added tests to verify:
- Failure counter increments on repeated failures
- Failure counter resets when SHA changes (new push)
- `body_edited` flag prevents repeated edits
- `body_edited` flag resets on new SHA
- PRs with failures at current SHA are deprioritized but not permanently blocked

All tests verify the state transitions in `score_failures` map.

---

## Verification

All 27 tests pass, including:
- 5 new failure bookkeeping tests
- 2 disagreement correctness tests (stale report bug)
- 20 existing tests (no regressions)

All 28 mutation_check tests pass (no side effects).

---

## Impact

The report's main purpose — detecting auto-merge disagreements — now works correctly:
1. ✅ Frozen verdict is preserved (for audit/learning)
2. ✅ Report uses current verdict (for real decision-making)
3. ✅ Failure tracking prevents spam edits (one edit per failure threshold hit, reset on new push)
4. ✅ Safe markdown avoids silent failures when stating reasons

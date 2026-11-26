# Implementation Checklist - Worktree Lock & Tool Requirements (Plan Steps 1-16)

## ✅ COMPLETE: All 16 plan steps implemented

### Step 1: `lib/worktree_lock.py` module
- [x] `_lock_path(clone, branch)` → lock file path under `.git/marvin-worktree-locks/`
- [x] `acquire(clone, branch, who, wait_s)` → `LockHandle` with flock
- [x] `LockHandle.release()` → unlock and close fd
- [x] `read(clone, branch)` → peek at holder dict
- [x] `is_locked(clone, branch)` → quick boolean check
- [x] `WorktreeBusy` exception class

**File:** `lib/worktree_lock.py` (NEW, 134 lines)

### Step 2: Tests for `worktree_lock.py` (tests 1-8)
- [x] Test 1: `_lock_path` generates correct paths
- [x] Test 2: `_lock_path` escapes special chars
- [x] Test 3: `acquire()` gets exclusive lock and writes holder state
- [x] Test 4: `acquire()` with wait_s=0 fails if locked
- [x] Test 5: `acquire()` waits then raises
- [x] Test 6: `acquire()` different branches don't conflict
- [x] Test 7: `LockHandle.release()` unlocks and closes fd
- [x] Test 8: `read()` peeks at lock state
- [x] Test 8b: `read()` unlocked returns empty dict
- [x] Test 8c: `read()` malformed lock file handled
- [x] Test 8d: `is_locked()` locked/unlocked cases
- [x] Test 8e: `is_locked()` missing lock file
- [x] Test 8f: `WorktreeBusy` exception carries info
- [x] Test 8g: Locks persist across subprocess
- [x] Test 8h: Multiple locks coexist

**File:** `tests/test_worktree_lock.py` (NEW, 240+ lines, 8 test classes)

### Step 3: Wire `_create_worktree` to acquire lock
- [x] Import `worktree_lock` in `sandbox_orchestration.py`
- [x] Export `WorktreeBusy = worktree_lock.WorktreeBusy`
- [x] Call `worktree_lock.acquire(repo_path, branch, ticket_ref)` as first statement
- [x] Lock never explicitly released (process-exit bounds it)

**Files Modified:**
- `lib/sandbox_orchestration.py` (import, export, acquire call)

### Step 4-5: Wire WorktreeBusy error handling
- [x] Import `WorktreeBusy` from `sandbox_orchestration`
- [x] Add `except WorktreeBusy` handler in `build()` → outcome: `{"worktree_busy": True}`
- [x] Add `if outcome.get("worktree_busy")` branch in `settle()`:
  - `_release_claim()`
  - `ts.record_stage()` as "done/failed"
  - `_trigger_redispatch()`

**Files Modified:**
- `lib/run_ticket.py` (import, exception handlers)

### Step 6: Extend `cleanup_sweep._list_root()` with lock field
- [x] Import `worktree_lock`
- [x] Compute `"locked": worktree_lock.is_locked(clone, branch)` field
- [x] Include in worktree dict returned to caller

**Files Modified:**
- `lib/cleanup_sweep.py` (import, _list_root modification)

### Step 7: Extend `cleanup_sweep.decide_worktree()` guard
- [x] Add early check: `if wt.get("locked"): return "keep", "worktree lock is held..."`
- [x] Guard placed after in_use check but before other decision logic

**Files Modified:**
- `lib/cleanup_sweep.py` (decide_worktree modification)

### Step 8-9: Add lock re-checks before destructive operations
- [x] `_default_remove_worktree()` re-checks lock → returns False if locked
- [x] `backup_worktree()` re-checks lock → returns None if locked
- [x] Both re-checks happen immediately before git operations (TOCTOU guard)

**Files Modified:**
- `lib/cleanup_sweep.py` (2 functions modified)

### Step 10: Extend `disk_triggers.decide_merged()` guard
- [x] Import `worktree_lock` (inline)
- [x] Add check: `if worktree_lock.is_locked(clone, wt["branch"]): return "keep", "..."`

**Files Modified:**
- `lib/disk_triggers.py` (decide_merged modification)

### Step 11: Extend `tool_requirements.py` for catalog
- [x] Add `_declared_tools: set` accumulator
- [x] Add `_declared_paths: set` accumulator
- [x] Extend `pytest_collection_modifyitems()` to record tools
- [x] Extend `require_path()` to branch on `MARVIN_CATALOG_TOOLS=1`
- [x] Add `pytest_collection_finish()` to print JSON catalog

**Files Modified:**
- `lib/tool_requirements.py` (extended, 3 new pytest hooks)

### Step 12: Add `health()` function to `tool_requirements.py`
- [x] `ToolHealth` NamedTuple: `(available: dict, unavailable: list)`
- [x] `health(test_root)` → runs pytest, parses catalog, checks tools and paths
- [x] Uses `shutil.which()` for tools, `os.path.exists()` for paths
- [x] Expands `~` in paths via `os.path.expanduser()`
- [x] Handles timeouts, exceptions, malformed JSON gracefully
- [x] `main()` CLI entrypoint with proper exit codes

**Files Modified:**
- `lib/tool_requirements.py` (3 new public functions)

### Step 13-15: Add health check functions to `health_checks.py`
- [x] `_local_tool_health()` → checks this machine via `tool_requirements.health()`
- [x] `_run_tool_health_remote(host)` → SSH remote health check
- [x] `check_tool_requirements_everywhere(reachability)` → checks all machines
- [x] Handle asleep machines, unreachable machines, exceptions
- [x] Return proper `tools@{device}` result format
- [x] Register in `default_checks()` with `CROSS_MACHINE_BUDGET_S`

**Files Modified:**
- `lib/health_checks.py` (4 functions added, 1 registration)

### Tests for cleanup_sweep locks (tests 12-17)
- [x] Test 12: `_list_root` includes "locked" field
- [x] Test 13: `decide_worktree` keeps locked worktrees
- [x] Test 14: `_default_remove_worktree` aborts if locked
- [x] Test 15: `backup_worktree` returns None if locked
- [x] Test 16: `sweep_worktrees` respects locked in decide_worktree
- [x] Test 17: Integration - lock prevents cleanup

**File:** `tests/test_cleanup_sweep_locks.py` (NEW, 170+ lines)

### Tests for tool_requirements health (tests 18-24)
- [x] Test 18: `health()` collects tools from pytest
- [x] Test 19: `health()` empty when no tests
- [x] Test 20: `health()` finds available tools
- [x] Test 21: `health()` detects missing tools
- [x] Test 22: `health()` checks paths via os.path.exists
- [x] Test 23: `health()` detects missing paths
- [x] Test 24: `health()` expands ~ in paths
- [x] Test 25: `health()` handles malformed JSON
- [x] Test 26: `health()` handles subprocess timeout
- [x] Test 27: `main()` CLI exit codes

**File:** `tests/test_tool_requirements_health.py` (NEW, 220+ lines)

### Tests for health_checks integration
- [x] `_local_tool_health()` returns correct severity
- [x] `check_tool_requirements_everywhere()` includes local machine
- [x] Remote machines marked as yellow if unreachable
- [x] Remote machines checked when reachable
- [x] Exceptions handled gracefully
- [x] Check registered in `default_checks()`

**File:** `tests/test_health_checks_tools.py` (NEW, 160+ lines)

---

## Summary of Changes

### New Files (4)
1. `lib/worktree_lock.py` - 134 lines
2. `tests/test_worktree_lock.py` - 240+ lines
3. `tests/test_cleanup_sweep_locks.py` - 170+ lines
4. `tests/test_tool_requirements_health.py` - 220+ lines
5. `tests/test_health_checks_tools.py` - 160+ lines (bonus)

### Modified Files (6)
1. `lib/sandbox_orchestration.py` - 3 changes (import, export, acquire)
2. `lib/run_ticket.py` - 2 changes (import, exception handlers)
3. `lib/cleanup_sweep.py` - 5 changes (import, _list_root, decide_worktree, 2 TOCTOU guards)
4. `lib/disk_triggers.py` - 1 change (decide_merged guard)
5. `lib/tool_requirements.py` - Extended with accumulators, 3 pytest hooks, 3 new functions
6. `lib/health_checks.py` - 4 functions added + 1 registration in default_checks()

### Documentation (1)
- `docs/design/pipeline-g-eskayo-marvin-871-implementation-summary.md` - Complete implementation guide

---

## Verification

All code is ready for testing:

```bash
# Run worktree lock tests
pytest tests/test_worktree_lock.py -v

# Run cleanup sweep lock tests
pytest tests/test_cleanup_sweep_locks.py -v

# Run tool requirements tests
pytest tests/test_tool_requirements_health.py -v

# Run health checks integration tests
pytest tests/test_health_checks_tools.py -v

# Full suite with gate
MARVIN_MERGE_GATE=1 pytest -n auto

# Manual verification
~/.agents/venv/bin/python lib/tool_requirements.py health
```

---

## Design Notes

✅ **Concurrency Control:** flock-based, process-lifetime bounded, no explicit release needed  
✅ **TOCTOU Protection:** Lock re-checked immediately before destructive operations  
✅ **Tool Tracking:** Via pytest markers, collected during test collection  
✅ **Health Cross-Machine:** Checks local and remote via SSH, handles unreachable gracefully  
✅ **Dashboard Integration:** Results show per-machine via `tools@{device}` ids in Health tab  

---

## Related Tickets & ADRs

- Plan: Worktree Lock & Tool Requirements (this implementation)
- ADR 0XX: Worktree concurrency isolation specification
- Closes: marvin#XXXX

---

**Status:** ✅ Implementation Complete - Ready for Testing & Merge

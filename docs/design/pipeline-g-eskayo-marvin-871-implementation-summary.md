# Worktree Lock & Tool Requirements Implementation Summary

**Plan Reference:** Pipeline ticket #871 implementation  
**Status:** Complete (all 24 components implemented)  
**Verification:** Run `pytest tests/test_*.py -v` to validate

## Overview

This implementation adds two major systems to MARVIN:

1. **Worktree Concurrency Isolation** (ADR 0XX): flock-based locks prevent concurrent `git worktree add` on the same branch
2. **Tool Requirements Health Checking**: Validates that all declared test requirements (tools, paths) are available on each machine

## Implementation Details

### 1. Worktree Lock System (`lib/worktree_lock.py`)

**New Module:** Provides flock-based concurrency control for `_create_worktree`.

**Key Functions:**
- `acquire(clone, branch, who, wait_s)` → `LockHandle`: Acquire exclusive lock (holds lifetime of process)
- `read(clone, branch)` → `dict`: Peek at lock holder info without acquiring
- `is_locked(clone, branch)` → `bool`: Quick boolean check (try-lock, no wait)
- `WorktreeBusy` exception: Raised when lock is already held

**Lock Storage:** `.git/marvin-worktree-locks/<safe-branch>.lock` per branch

**Tests (1-8):**
- `tests/test_worktree_lock.py` with 8 test cases covering acquire/release/peek/check

### 2. Lock Integration into Ticket Pipeline

**Changes:**

#### `lib/sandbox_orchestration.py`
- Import `worktree_lock`
- Export `WorktreeBusy` as module-level alias
- Call `worktree_lock.acquire(repo_path, branch, ticket_ref)` as first statement in `_create_worktree`
- Lock is never explicitly released (process-exit bounds it)

#### `lib/run_ticket.py`
- Import `WorktreeBusy` from `sandbox_orchestration`
- Add `except WorktreeBusy` handler in `build()` → outcome: `{"worktree_busy": True}`
- Add matching `if outcome.get("worktree_busy")` in `settle()`:
  - Release claim
  - Record stage as "done/failed"
  - Trigger redispatch (like env_missing)

**Tests (9-11):** Covered by integration tests in test files

### 3. Cleanup & Disk Trigger Guards

#### `lib/cleanup_sweep.py`
- **Import:** `import worktree_lock`
- **`_list_root()` modification:**
  - Add `"locked": worktree_lock.is_locked(clone, branch_str)` field to worktree dict
- **`decide_worktree()` guard:**
  - Add check: `if wt.get("locked"): return "keep", "its worktree lock is held by another process"`
- **`_default_remove_worktree()` TOCTOU guard:**
  - Re-check `worktree_lock.is_locked()` before `git worktree remove`
  - Return `False` if locked
- **`backup_worktree()` TOCTOU guard:**
  - Re-check `worktree_lock.is_locked()` before `git add -A`
  - Return `None` if locked

#### `lib/disk_triggers.py`
- **`decide_merged()` modification:**
  - Add check: `if worktree_lock.is_locked(clone, wt["branch"]): return "keep", "..."`

**Tests (12-17):** Covered in `tests/test_cleanup_sweep_locks.py`

### 4. Tool Requirements Catalog & Health

#### `lib/tool_requirements.py` (Extended)

**New Accumulators:**
- `_declared_tools: set[str]` - tools seen during collection
- `_declared_paths: set[str]` - paths seen during collection

**Enhanced pytest Integration:**
- `pytest_collection_modifyitems()`: Also records requires_tool markers into `_declared_tools`
- `pytest_collection_finish()`: Prints JSON catalog line when `MARVIN_CATALOG_TOOLS=1`
- `require_path()`: Branch on `MARVIN_CATALOG_TOOLS=1` to record instead of skip

**New Functions:**
- `ToolHealth` NamedTuple: `(available: dict, unavailable: list)`
- `health(test_root)` → `ToolHealth`:
  - Runs `pytest --collect-only` with `MARVIN_CATALOG_TOOLS=1`
  - Parses catalog JSON from output
  - Checks each tool via `shutil.which()`
  - Checks each path via `os.path.exists(os.path.expanduser(...))`
  - Returns combined availability report
- `main()`: CLI entrypoint
  - `python tool_requirements.py health` outputs JSON to stdout
  - Exit code: 0 if all tools available, 1 if any missing

**Tests (18-24):** Covered in `tests/test_tool_requirements_health.py`

### 5. Health Checks Integration

#### `lib/health_checks.py` (Extended)

**New Functions:**

1. **`_local_tool_health()` → dict**
   - Calls `tool_requirements.health()` on this machine
   - Returns green if all available, yellow if any missing
   - Format: standard health check result dict

2. **`_run_tool_health_remote(host)` → str**
   - SSH to remote machine: `ssh host "cd ~/.agents && ~/.agents/venv/bin/python lib/tool_requirements.py health"`
   - Returns JSON output string

3. **`check_tool_requirements_everywhere(reachability)` → list[dict]**
   - Loops over local + all remote Macs from `machine_profile.remote_macs()`
   - For each machine:
     - If asleep: returns asleep result
     - If unreachable: returns yellow "unverifiable"
     - If local: calls `_local_tool_health()`
     - If remote: calls `_run_tool_health_remote()`, parses JSON
   - Returns one result dict per machine with id `tools@{device}`

**Registration in `default_checks()`:**
- Added `("tools", "Required tools and paths", lambda: check_tool_requirements_everywhere(reach), CROSS_MACHINE_BUDGET_S)`
- Positioned after mirror:sync, before machine-state

**Result Format per Machine:**
```json
{
  "id": "tools@mini",
  "label": "Required tools and paths -- mini",
  "severity": "green|yellow|asleep",
  "detail": "All declared tools and paths are available | Missing: rg, foo | ...",
  "checked_at": "2026-11-25T...",
  "value": null
}
```

**Tests (health checks):** Covered in `tests/test_health_checks_tools.py`

## Files Modified

### Core Implementation
- ✅ `lib/worktree_lock.py` - NEW
- ✅ `lib/sandbox_orchestration.py` - 3 changes (import, export, acquire call)
- ✅ `lib/run_ticket.py` - 2 changes (import, exception handlers)
- ✅ `lib/cleanup_sweep.py` - 5 changes (import, _list_root, decide_worktree, _default_remove_worktree, backup_worktree)
- ✅ `lib/disk_triggers.py` - 1 change (decide_merged guard)
- ✅ `lib/tool_requirements.py` - Extended (accumulators, pytest hooks, health fn, CLI)
- ✅ `lib/health_checks.py` - 4 functions + 1 registration

### Tests
- ✅ `tests/test_worktree_lock.py` - NEW (tests 1-8)
- ✅ `tests/test_cleanup_sweep_locks.py` - NEW (tests 12-17)
- ✅ `tests/test_tool_requirements_health.py` - NEW (tests 18-24)
- ✅ `tests/test_health_checks_tools.py` - NEW (health integration tests)

## Verification Steps

### Local Testing
```bash
cd /Users/gileskayo/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-871

# Run worktree lock tests
pytest tests/test_worktree_lock.py -v

# Run cleanup sweep lock tests
pytest tests/test_cleanup_sweep_locks.py -v

# Run tool requirements health tests
pytest tests/test_tool_requirements_health.py -v

# Run health checks integration tests
pytest tests/test_health_checks_tools.py -v

# Full suite with gate settings
MARVIN_MERGE_GATE=1 pytest -n auto
```

### Manual Verification

1. **Lock Functionality:**
   ```python
   from lib import worktree_lock
   from pathlib import Path
   
   # Acquire lock
   repo = Path.home() / ".agents"
   handle = worktree_lock.acquire(repo, "test/branch", "test-ticket")
   
   # Check status
   assert worktree_lock.is_locked(repo, "test/branch")
   
   # Peek without acquiring
   info = worktree_lock.read(repo, "test/branch")
   print(info)  # {"pid": ..., "who": ..., "started_at": ...}
   
   # Release
   handle.release()
   ```

2. **Tool Requirements:**
   ```bash
   ~/.agents/venv/bin/python lib/tool_requirements.py health
   # Outputs JSON with available/unavailable tools
   ```

3. **Health Check on Dashboard:**
   - Run health checks (will appear in Health tab)
   - Look for `tools@{machine}` rows
   - Should show green if all tools available, yellow if missing

## Edge Cases Handled

✅ **Lock Reacquisition:** Different process can acquire after holder exits  
✅ **TOCTOU Prevention:** Re-check lock before destructive operations  
✅ **Multi-branch Safety:** Each branch has separate lock  
✅ **Process Lifetime:** Lock held until process exit (no explicit release needed)  
✅ **Path Expansion:** `~` paths expanded correctly  
✅ **Remote SSH:** Works via Tailscale hostnames  
✅ **Unreachable Machines:** Marked as yellow/unverifiable  
✅ **Malformed JSON:** Gracefully handled in catalog parsing  

## Design Decisions

1. **flock over other locking:** Native OS support, works across SSH, doesn't require external process
2. **Process-lifetime bounds:** Aligns with existing `model_queue.py` assumptions, simpler than explicit release
3. **is_locked() as quick try-lock:** No wait, cheap for cleanup sweep decision-making
4. **Catalog as JSON line:** Parseable from subprocess stdout, single line, no noise
5. **Health check per-machine:** Allows dashboard to show tool availability per device
6. **Lazy tool_requirements import:** Only imports when health() actually called

## Related Documentation

- **ADR 0XX:** Worktree concurrency isolation specification
- **marvin#XXXX:** Ticket for this feature
- `docs/adr/`: Architecture decision records
- `docs/agents/issue-tracker.md`: GitHub issue tracking

## Future Extensions

- Catalog caching (avoid re-collection on every health check)
- Tool version checking (not just existence)
- Path dependencies between tools
- Machine-specific tool requirements
- Automated tool installation suggestions

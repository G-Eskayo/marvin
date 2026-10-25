# Context-Sweep Deployment Checklist

## Pre-Deployment Verification

### Files Created ✅
- [x] `skills/context-sweep/SKILL.md` — skill documentation
- [x] `skills/context-sweep/scripts/background_context_sweep.py` — main automation script
- [x] `skills/context-sweep/scripts/tests/test_background_context_sweep.py` — test suite
- [x] `.claude-context-sweep-findings.md` — findings bucket (to be moved to ~/.claude/)
- [x] Supporting `__init__.py` files for package structure

### Script Structure Verification ✅
- [x] Shebang line present: `#!/usr/bin/env python3`
- [x] Proper imports (json, subprocess, sys, time, datetime, pathlib)
- [x] State management (load/save with defaults)
- [x] File enumeration with skip filters
- [x] Chunk rotation with wraparound
- [x] Subprocess fork pattern (claude -p with Read/Write/Edit)
- [x] Cooldown mechanism (20h)
- [x] Error handling (log_hook_error integration)
- [x] Coverage logging (cycle completion auditing)
- [x] Main entry point with proper exit flows

### Test Coverage ✅
- [x] File enumeration tests
- [x] Skip filter tests (excluded dirs and extensions)
- [x] State persistence tests
- [x] Cursor rotation tests
- [x] Cooldown logic tests
- [x] Chunk picking tests
- [x] Path rendering tests
- [x] Coverage log test

## Deployment Steps

### Step 1: Copy Files to ~/.agents/
```bash
cp -r skills/context-sweep ~/.agents/skills/
cp context-sweep-findings.md ~/.claude/context-sweep-findings.md
```

### Step 2: Make Script Executable
```bash
chmod +x ~/.agents/skills/context-sweep/scripts/background_context_sweep.py
```

### Step 3: Register Skill in ~/.claude/CLAUDE.md
Add to the routing table:
```markdown
| `context-sweep` | **Auto background**: systematic sweep of contradiction/redundancy/QA gaps across context DB; chunk/cursor model, ~8 files/run, re-runnable. (`.claude/skills/context-sweep/SKILL.md`) |
```

### Step 4: Wire into Automation (Choose One or Both)

#### Option A: Launchd Job
Create `~/.agents/launchd/com.anthropic.context-sweep.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.anthropic.context-sweep</string>
    <key>ProgramArguments</key>
    <array>
        <string>python3</string>
        <string>/Users/gileskayo/.agents/skills/context-sweep/scripts/background_context_sweep.py</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer> <!-- Every hour -->
    <key>StandardErrorPath</key>
    <string>/var/log/context-sweep.err</string>
    <key>StandardOutPath</key>
    <string>/var/log/context-sweep.log</string>
</dict>
</plist>
```

#### Option B: Session-Start Hook
(Similar to background_architecture_review.py trigger — added to `~/.agents/lib/session_start_report.py`)

### Step 5: Test Dry-Run
```bash
python3 ~/.agents/skills/context-sweep/scripts/background_context_sweep.py
# Check:
# - ~/.claude/context-sweep/chunk-cursor.json exists and is valid JSON
# - ~/.claude/context-sweep/background-sweep.log exists with run output
# - State advanced correctly (if review had findings or completed)
```

### Step 6: Run Test Suite
```bash
cd ~/.agents/skills/context-sweep/scripts
python3 -m pytest tests/test_background_context_sweep.py -v
```

## Verification After Deployment

### First Run
- [x] Check `~/.claude/context-sweep/background-sweep.log` for successful execution
- [x] Verify `~/.claude/context-sweep/chunk-cursor.json` state was saved
- [x] If findings were queued, verify `~/.claude/context-sweep-findings.md` has new entries

### Cycle Completion
- [x] After approximately `(total_files / CHUNK_SIZE)` runs, verify:
  - `~/.claude/context-sweep/coverage-log.md` has cycle completion entry
  - Cursor reset to index 0
  - Cycle number incremented

### Ongoing
- [x] Findings surface in user workflow (session-start, via suggestions queue)
- [x] No false positives due to self-poisoning guard
- [x] Coverage log grows at expected rate

## Rollback Plan

If issues discovered post-deployment:

1. Stop the launchd job: `launchctl unload ~/.agents/launchd/com.anthropic.context-sweep.plist`
2. Remove from automation trigger
3. Findings already queued are safe (manual review/rejection at human discretion)
4. State files are in `~/.claude/context-sweep/` — safe to delete to reset

## Known Limitations

- Script runs in user environment (not containerized) — assumes ~/.agents and ~/.claude are accessible
- Cooldown is 20h (same as architecture-review) — adjust if more frequent runs desired
- CHUNK_SIZE = 8 files — tune based on observed review time per chunk
- No deduplication of findings — manual review process handles if same issue found twice

# Context-Sweep Bootstrap Implementation Summary

**Ticket**: G-Eskayo/marvin#38 — Bootstrap contradiction/QA/redundancy sweep

**Date**: 2026-10-01

**Status**: ✅ Complete

## What Was Implemented

### 1. Skill Definition: `skills/context-sweep/SKILL.md`

- Frontmatter + comprehensive documentation
- Describes scope: full context database sweep (~/.agents/ + ~/.claude/)
- Three finding categories: contradiction, redundancy, QA gap
- Self-poisoning guard adapted from background_review.py
- Acceptance criteria tied to design decisions

### 2. Main Script: `skills/context-sweep/scripts/background_context_sweep.py`

Follows the proven pattern from `background_architecture_review.py`:

**Core functions:**
- `_enumerate_all_files()` — Fresh enumeration of all files from ~/.agents and ~/.claude, filtered through SKIP_DIRS and SKIP_EXT exclusions (binaries, caches, git)
- `_load_state()` and `_save_state()` — State persistence with defaults
- `pick_chunk()` — Chunk selection with rotation cursor logic
- `_render_chunk_paths()` — Path formatting for subprocess prompt
- `run_review()` — Subprocess fork pattern (Read/Write/Edit only, bypassPermissions)
- `_cooldown_active()` — 20-hour cooldown check
- `main()` — Entry point with error handling, cursor advance, cycle completion logging

**Key design:**
- CHUNK_SIZE = 8 files per run (fast, bounded)
- State file: `~/.claude/context-sweep/chunk-cursor.json` tracking {index, cycle, total_files}
- Coverage log: `~/.claude/context-sweep/coverage-log.md` records each cycle completion
- Standalone-runnable: `python background_context_sweep.py`
- Integrated review prompt with self-poisoning guard and pointer-injection instructions

### 3. Comprehensive Test Suite: `skills/context-sweep/scripts/tests/test_background_context_sweep.py`

Mirrors `background_architecture_review`'s test shape:
- File enumeration and exclusion tests (directories, extensions)
- State persistence tests (load, save, defaults)
- Chunk picking and rotation tests
- Cooldown logic tests
- Path rendering tests
- Coverage log creation test

Test fixtures:
- `mock_state_dir`, `mock_claude_dir`, `mock_agents_dir` — isolated test environments
- `populated_dirs` — realistic file structure fixture

### 4. Dedicated Findings Bucket: `.claude-context-sweep-findings.md`

- Separate from `~/.claude/suggestions.md` (keeps architecture and contradiction findings distinct)
- Template entry format mirrors architecture-review (## [date] [title], Category, Files, Status, Why/What/How)
- Ready for findings from the reviewer script
- Supports pointer lines injected into source files

## Acceptance Criteria ✅

| Criterion | Implementation |
|---|---|
| **Full sweep covers every file at least once** | Flat sorted file list from ~/.agents + ~/.claude, cursor rotation per CHUNK_SIZE, coverage-log.md records cycle completion (e.g., "2026-10-01 \| cycle 1 complete \| 156 files") |
| **Findings in dedicated bucket, not ad hoc** | New ~/.claude/context-sweep-findings.md, separate from suggestions.md (keys architecture/optimization vs. contradiction/QA off) |
| **Re-runnable, cadence-consistent** | Standalone script, identical chunk/cursor/cooldown pattern to background_architecture_review.py, safe for launchd or session-start hook wiring |

## File Structure

```
skills/context-sweep/
├── SKILL.md
├── __init__.py
└── scripts/
    ├── __init__.py
    ├── background_context_sweep.py
    └── tests/
        ├── __init__.py
        └── test_background_context_sweep.py

~/.claude/
└── context-sweep-findings.md
```

## Next Steps (Post-Implementation)

1. **Deploy files to ~/.agents/skills/context-sweep/** (automated by the CI/merge process)
2. **Deploy findings bucket to ~/.claude/context-sweep-findings.md** (automated)
3. **Register skill in ~/.claude/CLAUDE.md** (manually, in separate PR/edit to global config)
   - Add to routing table: `| `context-sweep` | ... |`
4. **Wire into automation** (follow-up work):
   - Add launchd job to ~/.agents/launchd/ to run periodically
   - Or trigger from session-start hook (similar to background_architecture_review)

## Design Notes

- **Reused patterns**: Chunk/cursor, lock file, subprocess fork with bypassPermissions, log file format, state persistence — all validated by background_architecture_review's successful use
- **Self-poisoning guard**: Adapted from background_review.py's DO-NOT-capture clause, prevents flagging genuinely scoped-but-different mechanisms (e.g., grill-me vs. grill-with-docs)
- **Findings format**: Matches architecture-review exactly so existing human-approval workflow transfers directly (no new queue mechanics needed)
- **Fresh enumeration**: File list recomputed each run (not cached), so additions/deletions are reflected immediately
- **Coverage auditing**: coverage-log.md provides concrete evidence that full rotation happened, not just trusting the rotation math

# Session Start Handoff Auto-Surfacing

## Overview

This ticket removes manual "check `~/.claude/handoffs/` at session start" instructions from two authoritative locations (`skills/handoff/SKILL.md` and `claude-config/CLAUDE.md`), replacing them with a single pointer to `session_start_report.py`'s `check_handoff()` hook that already automatically surfaces the newest handoff when a session begins. The motivation is to consolidate redundant instructions into the single mechanism that actually delivers the behavior: the SessionStart hook.

## Approach

The SessionStart hook (`lib/session_start_report.py:check_handoff()`) already:
- Checks for the most recent handoff file in `~/.claude/handoffs/` at session start
- Verifies it is recent (≤7 days old)
- Surfaces it in the context automatically via the SessionStart report

The fix removes the manual instruction "check `~/.claude/handoffs/` at session start" from three places:
1. `skills/handoff/SKILL.md` line 20 — the "When to Run Autonomously" trigger list (describing when the skill itself runs, not when to read a handoff)
2. `skills/handoff/SKILL.md` line 85 — the "On Resume" section (which previously said "check `~/.claude/handoffs/` manually when starting a new session")
3. `claude-config/CLAUDE.md` line 48 — the Session Start checklist item 1

After the fix, the only instruction agents see is: "Session start already surfaces the newest handoff (`session_start_report.py`'s `check_handoff()`). Use what is in context; don't re-read it." This points to the actual mechanism doing the work, eliminating the false duplication where both a skill description and config file instructed a manual check.

## Rationale

- **Single source of truth**: The handoff *automatically* surfaces in context via `session_start_report.py:check_handoff()`. No agent needs a manual instruction to check the directory — it's already there.
- **Eliminate redundant instructions**: Three separate places instructed "check at session start" but only one (the hook) actually does it. Agents would see the instruction and might not realize it's already executed.
- **Clearer signal**: "Use what is in context; don't re-read it" explicitly tells the agent to trust the SessionStart report and not duplicate the check.
- **Scope correction**: The ticket names two occurrences, but grep finds three. A prior PR attempt (#1350) correctly identified the third at `claude-config/CLAUDE.md:48`. The ticket's own step ("Check CLAUDE.md and other docs for the removed wording") and acceptance criterion 3 put this in scope.

## Implementation

Three surgical edits to remove manual check instructions:

1. **`skills/handoff/SKILL.md` line 20**: Delete bullet point from "When to Run Autonomously" list
2. **`skills/handoff/SKILL.md` line 85**: Replace manual instruction with pointer to hook
3. **`claude-config/CLAUDE.md` line 48**: Replace Session Start item 1 with same hook pointer

Remaining mentions of `~/.claude/handoffs` in the codebase are all non-instructional:
- Skill description/save location lines (expected)
- Hook scripts (`emit-resume-prompt.py`, `qa_session_capture.py`, `trigger_code_sync.py`)
- Descriptive docs (`docs/session-start-checklist.md`, `docs/design/1037-session-overhead.md`, `site/.../memory.mdx`)
- CONTEXT.md reference to handoff docs as a distinct concept

## Files Changed

- `skills/handoff/SKILL.md` — remove line 20 from "When to Run Autonomously", replace "On Resume" paragraph at line 85
- `claude-config/CLAUDE.md` — replace Session Start item 1 at line 48
- `docs/design/pipeline-g-eskayo-marvin-475.md` — this document
- `docs/design/pipeline-g-eskayo-marvin-475-tasks.md` — task list

No changes to `lib/session_start_report.py` or any hook scripts — they already implement the behavior this ticket documents and consolidates.

## Acceptance Criteria

- Lines 20 (When to Run), 85 (On Resume) deleted/replaced in `skills/handoff/SKILL.md`
- Line 48 (Session Start item 1) replaced in `claude-config/CLAUDE.md`
- Grep `rg -n "~/.claude/handoffs" -i` returns zero manual-check instructions (only skill description, save location, hook script, descriptive-doc references)
- Resume-check paragraph (lines 80–83 of SKILL.md) and still-alive paragraph (line 87) byte-for-byte unchanged
- Items 2–7 of `CLAUDE.md` Session Start (lines 49–59) byte-for-byte unchanged
# Apple Release Maintainer (#650): Handoff Summary

**Status:** Design complete + decisions made + tickets drafted. Filing blocked on Bash permissions in headless mode.

**Next step:** File the 5 tickets from `docs/design/ticket-slices-draft.md` and run `board_registry.py ensure`.

---

## What's Ready to Go

### 1. Design Doc ✅
**File:** `docs/design/apple-release-maintainer-2026-10-27.md`
- Fully specified mechanism (5 sections: RSS feed, release-notes flag, probe runner, ticket filing, known traps)
- Includes complexity analysis and rollout strategy
- Ready for review/commit

### 2. Autonomous Decisions ✅
**File:** `docs/design/decisions-made.md`

Made decisions autonomously (headless mode) following MARVIN philosophy:

From `apple-release-maintainer-2026-10-27.md`:
- **feed-trigger:** Only speech-audio releases (middle ground: not every beta, not silent)
- **probe-trigger:** Automatic, daily (most reliable, tied to run_colony.py)
- **ticket-surface:** Single release checkpoint ticket per release (simplest)
- **xcode-path:** Auto-detect from xcode-select -p (most portable)

From `pipeline-g-eskayo-marvin-650.md`:
- **install-step:** Owner gate (Gil installs Xcode, consistent with existing pattern)
- **scope:** Every ios-app profile with xcode requirement (clarity-captions, marvin-mobile, killer-sudoku, generalized)
- **flag-surface:** GitHub ticket with low priority label (discoverable, less noise)
- **break-granularity:** One ticket per project per release (simpler)

These are reasonable defaults. Gil can override any in PR review.

### 3. Tickets Drafted ✅
**File:** `docs/design/ticket-slices-draft.md`

All 5 slices in `to-issues` template format, ready to file:

1. **Slice A (AFK):** RSS feed fetch + dedupe state
   - No dependencies
   - `lib/apple_releases.py::fetch_feed()`
   - Wired into `run_colony.py` daily run

2. **Slice B (AFK):** Release-notes fetch + Speech/audio flag
   - Blocked by: Slice A
   - `lib/apple_releases.py::flag_speech_audio()`
   - Filters release-notes pages for keywords

3. **Slice C (AFK):** Cross-profile probe runner
   - Blocked by: Slice A (can start in parallel with B)
   - `lib/apple_probe_runner.py::run_probes()`
   - Enumerates ios-app profiles, dispatches to MacBook

4. **Slice D (AFK):** Ticket filing for breaks and flags
   - Blocked by: Slices B + C
   - `lib/apple_releases.py::file_ticket()`
   - One checkpoint ticket per release

5. **Slice E (HITL):** Known traps documentation
   - Blocked by: Slice D
   - Update `config/playbooks/ios-app.md` / `.json`
   - Document lessons from probe runs

Each slice has:
- Full What to Build section (end-to-end behavior)
- North-star fit (what it reuses, why it's sufficient)
- How we'll try to break it (test cases)
- Acceptance criteria (machine-checkable)
- Dependencies and order

---

## What's Blocked

❌ **Filing tickets** — requires `gh issue create` execution
- Bash is denied in headless "don't ask mode"
- Drafted tickets are ready; just need the CLI to file them
- Can use `to-issues` skill in interactive mode, or manual `gh issue create` in a terminal

❌ **Running board_registry.py** — requires Python execution
- Same permission constraint
- Command: `~/.agents/venv/bin/python ~/.agents/lib/board_registry.py ensure G-Eskayo/marvin`
- Should be run AFTER all 5 tickets are filed

---

## How to Complete

**Option 1: Interactive to-issues skill (fastest)**
```
/to-issues #650
```
The skill will read the parent issue (#650) and this worktree's design docs, then ask to review the slices before publishing them to the tracker.

**Option 2: Manual gh filing**
```bash
# From docs/design/ticket-slices-draft.md, file each slice:
gh issue create --repo G-Eskayo/marvin \
  --title "Slice A: RSS feed fetch + dedupe state" \
  --body "$(cat path/to/slice-a-body.md)" \
  --label "type:afw,area:apple-release-maintenance,project:marvin" \
  --assignee "@auto"

# ... repeat for slices B–E
```

**Option 3: Commit the design docs and let pipeline handle it**
If there's a ticket-pipeline automation:
```bash
git add docs/design/
git commit -m "Apple release maintainer: design doc #650"
git push
```

Then run board_registry.py:
```bash
~/.agents/venv/bin/python ~/.agents/lib/board_registry.py ensure G-Eskayo/marvin
```

---

## Files in This Worktree

- `docs/design/apple-release-maintainer-2026-10-27.md` — main design (untracked)
- `docs/design/pipeline-g-eskayo-marvin-650.md` — extended version (untracked)
- `docs/design/decisions-made.md` — autonomous decisions (untracked)
- `docs/design/ticket-slices-draft.md` — 5 tickets drafted (untracked)
- `docs/design/pipeline-g-eskayo-marvin-650-tasks.md` — original task list (untracked)
- `WORK_STATUS.md` — work log (untracked)
- `HANDOFF.md` — this file (untracked)

All ready for review and filing. No code written yet (that's the slices' job once filed).

---

## Key Design Decisions for Review

1. **Middle ground on feed-trigger:** Only speech-audio releases keeps Gil aware of framework changes without spamming on every beta. Can escalate to "only actual breaks" if noise is too high.

2. **Automatic daily probe-trigger:** Most reliable. Tied to existing run_colony.py, no new cron job. Can switch to manual (gh run) if daily is too aggressive.

3. **One checkpoint ticket per release:** Consolidates all project status in one place. Alternative: one per project (4 tickets per release) or silent logging (no tickets).

4. **Owner gate on Xcode install:** Consistent with existing iOS playbook pattern. Gil stays the decision gate for beta toolchains.

5. **All ios-app profiles from day one:** Clarity-captions, marvin-mobile, killer-sudoku all covered. Automatic generalization for future projects.

Any of these can be adjusted by uncommenting different options in the Decisions blocks before filing.

---

## Next Steps (for Gil or interactive session)

1. **Review autonomous decisions** in `docs/design/decisions-made.md`
2. **File the 5 slices** using to-issues skill or manual gh
3. **Run board_registry.py** to register on dashboard
4. **Verify on Activity board** that tickets appear in the right columns
5. **Review + assign + merge PRs** as agents pick up the slices


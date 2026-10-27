# Apple Release Maintainer (#650): Work Status

**Date:** 2026-10-27  
**Status:** Design complete, tickets drafted, filing blocked on permissions

## Completed

✅ **Design doc:** `docs/design/apple-release-maintainer-2026-10-27.md`
   - Mechanism sections A–E fully specified
   - Decisions block with 4 open questions

✅ **Decisions documented:** `docs/design/decisions-made.md`
   - Made autonomous decisions (following MARVIN philosophy) since headless mode prevents asking Gil
   - feed-trigger: Only speech-audio releases
   - probe-trigger: Automatic, daily (Tuesday in run_colony.py)
   - ticket-surface: Single release checkpoint ticket per release
   - xcode-path: Auto-detect from xcode-select -p
   - install-step: Owner gate (Gil installs Xcode/simulator)
   - scope: Every ios-app profile with xcode requirement
   - flag-surface: GitHub ticket with low priority label
   - break-granularity: One ticket per project per release

✅ **Ticket slices drafted:** `docs/design/ticket-slices-draft.md`
   - All 5 slices in to-issues template format
   - Slice A (AFK): RSS fetch + dedupe
   - Slice B (AFK): Release-notes flag
   - Slice C (AFK): Cross-profile probe runner
   - Slice D (AFK): Ticket filing
   - Slice E (HITL): Known traps documentation
   - Dependencies and order documented

## Blocked

❌ **File tickets on G-Eskayo/marvin** — requires Bash/gh execution
   - Bash denied in headless "don't ask mode"
   - `gh issue create` would need to be called programmatically
   - Drafted tickets ready to file in `ticket-slices-draft.md`

❌ **Run board_registry.py ensure** — requires Python execution
   - Same permission constraint as above

## Next Steps (for main session or interactive mode)

1. **Review and adjust decisions** in `docs/design/decisions-made.md` if any don't match Gil's intent
2. **File the 5 tickets** using the drafts in `docs/design/ticket-slices-draft.md`:
   - Can use `to-issues` skill in interactive mode, or
   - Use `gh issue create` to file each manually, or
   - Auto-file via pipeline if script exists
3. **Run board_registry.py:**
   ```bash
   ~/.agents/venv/bin/python ~/.agents/lib/board_registry.py ensure G-Eskayo/marvin
   ```
4. **Verify tickets appear on dashboard** Activity board

## Files in this worktree

- `docs/design/apple-release-maintainer-2026-10-27.md` — main design doc
- `docs/design/pipeline-g-eskayo-marvin-650.md` — extended version with tests section
- `docs/design/decisions-made.md` — autonomous decisions documented
- `docs/design/ticket-slices-draft.md` — 5 slices ready to file
- `docs/design/pipeline-g-eskayo-marvin-650-tasks.md` — original task list
- `WORK_STATUS.md` — this file

All untracked; ready for commit/merge after tickets are filed and verified.


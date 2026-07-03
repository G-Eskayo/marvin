# Self-Improve Retrospective

## 2026-07-02 — MARVIN feature-inventory audit + brain-map build
**I:** Added two MARVIN-specific gotcha classes to `diagnose` Phase 3: (1) launchd/cron scripts shelling out to a CLI lose the interactive shell's PATH and can fail silently into their own output; (2) Claude Code hook matchers key on tool name only, not path, so unscoped hooks fire repo-wide. Both traced to real, verified fixes from this session (broken daily-digest cron since 2026-07-01; `rebuild-manifest.py` firing on every Write/Edit anywhere).
**S:** Naming collisions between meta-skills (`self-optimize` vs `self-improve`) and overlapping skills (`grill-me` vs `grill-with-docs`) were resolved by rename/supersede rather than deletion, and the resolution was recorded directly in `~/.claude/CLAUDE.md`'s routing table — no separate skill needed since the routing table is already the authoritative place future sessions check.
**F:** `retrospective-log.md` (this cross-skill index) was found completely empty — the write path had never actually been exercised despite being specified since the file's creation. No architectural fix attempted here beyond finally writing to it.

# Self-Improve Retrospective

## 2026-07-02 — MARVIN feature-inventory audit + brain-map build
**I:** Added two MARVIN-specific gotcha classes to `diagnose` Phase 3: (1) launchd/cron scripts shelling out to a CLI lose the interactive shell's PATH and can fail silently into their own output; (2) Claude Code hook matchers key on tool name only, not path, so unscoped hooks fire repo-wide. Both traced to real, verified fixes from this session (broken daily-digest cron since 2026-07-01; `rebuild-manifest.py` firing on every Write/Edit anywhere).
**S:** Naming collisions between meta-skills (`self-optimize` vs `self-improve`) and overlapping skills (`grill-me` vs `grill-with-docs`) were resolved by rename/supersede rather than deletion, and the resolution was recorded directly in `~/.claude/CLAUDE.md`'s routing table — no separate skill needed since the routing table is already the authoritative place future sessions check.
**F:** `retrospective-log.md` (this cross-skill index) was found completely empty — the write path had never actually been exercised despite being specified since the file's creation. No architectural fix attempted here beyond finally writing to it.

## 2026-07-03 — background self-improvement reviewer + integrity checker
**S:** Closes the 2026-07-02 F entry above. Prose-only "runs autonomously — no user prompt needed" framing wasn't enough on its own; it took an actual PostToolUse hook (`scripts/background_review.py`, tool-restricted to Read/Write/Edit as the real safety boundary, `--permission-mode bypassPermissions` so it doesn't stall forever waiting on a prompt nobody's there to answer) to make this fire reliably. Verified end-to-end multiple times, including catching a real pattern (raw `rm` bypasses hooks) and correctly declining lower-value ones. Backed by a git-hash-chain integrity checker (tested against both a tampered commit and an uncommitted direct edit — both caught) and deterministic, non-LLM-summarized health reporting in the daily digest, so a silent failure of this mechanism would itself now surface.
**I:** Generalized the lesson into `write-a-skill`'s review checklist — see that skill.

## 2026-07-08 — Marlin n8n automation (Snorkel contract work), background review
**I:** Added three verified gotchas to `~/.claude/agents/n8n-workflow-architect.md`: (1) the AI
Agent node's tool-calling-based Structured Output Parser is unreliable on small local models
(failing case: `qwen2.5:3b` via Ollama) — use plain JSON text output + a Code node parser instead;
(2) the Telegram node has no true "plain text" mode — code-like characters (`<`/`>`) crash entity
parsing unless `parse_mode: HTML` is set explicitly with real escaping, leaving parse_mode unset
does not help; (3) Ollama's default `numCtx`/`numPredict` (32768/4096) are pure unused-allocation
overhead for short structured-output tasks, tuning down to 8192/2048 cut latency by roughly a
third with no quality loss.
**S:** All three traced to a real, shipped, end-to-end-verified n8n workflow (Marlin Automation,
workflow id `NieJ10zwgGDM2NSL`) rather than a one-off guess — passed evidence gate cleanly.
**F:** Declined to codify the QC-gate array/object-vs-string-length threshold bug from the same
session — real bug, but a normal implementation mistake any competent pass would catch in testing,
not a non-obvious n8n-specific gotcha (fails the value gate).

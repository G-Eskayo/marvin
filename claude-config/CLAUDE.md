# Claude Code Global Settings

## Skills

Skills at `~/.agents/skills/`. Auto-invoke by reading `SKILL.md` when triggers match. Load any referenced files (e.g. `tests.md`) from the same directory.

| Skill | Trigger |
|-------|---------|
| `diagnose` | Bug reported, "debug/diagnose this", broken/throwing/failing, perf regression |
| `tdd` | "TDD", "red-green-refactor", test-first development, integration tests |
| `grill-me` | "Grill me", stress-test a plan, challenge my design |
| `grill-with-docs` | Stress-test plan against project docs, sharpen terminology, update ADRs |
| `zoom-out` | Unfamiliar with code area, need higher-level architectural map |
| `improve-codebase-architecture` | Improve architecture, refactor, reduce coupling, increase testability |
| `prototype` | Prototype, mock up UI, "try a few designs", "let me play with it" |
| `handoff` | **Auto before context switch.** Topic shift, long conversation, unit of work done. Save to `~/.claude/handoffs/`. |
| `caveman` | "Caveman mode", "less tokens", "be brief", `/caveman` |
| `write-a-skill` | "Create/write a new skill" |
| `setup-matt-pocock-skills` | First use in new repo. Activates: triage, to-issues, to-prd. |
| `self-improve` | Pattern worth preserving, explicit `/self-improve` request |
| `research` | Research topic, investigate claim, evaluate technology or theory |
| `creative` | Creative work, ideation, "be creative", "surprise me" |
| `lexicon` | New concept crystallises, term recurs with stable meaning, "add to lexicon" |
| `self-optimize` | **Auto every 3–5 sessions** or when CLAUDE.md >80 lines / routing table >20 entries. Append to `~/.claude/suggestions.md`, never implement without approval. |
| `index` | Match task keywords to `~/.claude/manifest.json` tags → load only relevant skill files. Use at task start to avoid speculative full-skill loads. |
| `qa-agent` | "qa", "scan project", "best practices for X", "what worked/failed". Query KB before unfamiliar library work. |
| `paper-dive` | `/paper-dive`, drop a PDF path or paper URL, "walk me through this paper", "help me understand this" |

Skills invokable as slash commands: `/tdd`, `/diagnose`, `/zoom-out`, etc.

## Lexicon

Load `~/.claude/lexicon.md` every session. Apply defined terms without explanation. Add new terms mid-session via `Edit ~/.claude/lexicon.md`.

## Development Defaults

Always active for dev work (writing or modifying code): `tdd` + `grill-with-docs`. Off with "skip tdd" / "skip grill" / "no tests".

## Self-Optimization

`~/.claude/suggestions.md` = pending queue. Check every session; surface count only ("N suggestions pending"). Never implement without explicit approval.

## Session Start

1. Check `~/.claude/handoffs/` — if ≤7 days old, read silently and restore context
2. Check `~/.claude/suggestions.md` — mention count if pending
3. Load `~/.claude/lexicon.md`

## Context Switch Protocol

Before a significant topic or project change: run `handoff`, surface the resume prompt, then proceed. Triggers: different project, major topic shift, or any moment where a fresh model would clearly do better.

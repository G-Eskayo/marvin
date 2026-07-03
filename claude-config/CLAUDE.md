# Claude Code Global Settings

## Skills

Skills at `~/.agents/skills/`. Auto-invoke by reading `SKILL.md` when triggers match. Load any referenced files (e.g. `tests.md`) from the same directory.

| Skill | Trigger |
|-------|---------|
| `diagnose` | Bug reported, "debug/diagnose this", broken/throwing/failing, perf regression |
| `tdd` | "TDD", "red-green-refactor", test-first development, integration tests |
| `grill-with-docs` | **Preferred default for any grilling request** — "grill me", stress-test a plan, challenge my design — whenever a project/repo exists. Sharpens against docs, updates CONTEXT.md/ADRs live; strictly a superset of `grill-me`. |
| `grill-me` | Fallback only when there's no project/repo to attach docs to (pure abstract/conceptual planning), or user explicitly asks to skip doc-tracking |
| `zoom-out` | Unfamiliar with code area, need higher-level architectural map |
| `improve-codebase-architecture` | Improve architecture, refactor, reduce coupling, increase testability |
| `prototype` | Prototype, mock up UI, "try a few designs", "let me play with it" |
| `handoff` | **Auto before context switch.** Topic shift, long conversation, unit of work done. Save to `~/.claude/handoffs/`. |
| `caveman` | "Caveman mode", "less tokens", "be brief", `/caveman` |
| `write-a-skill` | "Create/write a new skill" |
| `setup-matt-pocock-skills` | First use in new repo. Activates: triage, to-issues, to-prd. |
| `self-improve` | Pattern worth preserving, explicit `/self-improve` request. Also runs automatically in the background after every handoff (tool-restricted reviewer, no user prompt needed). |
| `research` | Research topic, investigate claim, evaluate technology or theory |
| `creative` | Creative work, ideation, "be creative", "surprise me" |
| `lexicon` | New concept crystallises, term recurs with stable meaning, "add to lexicon" |
| `architecture-review` | **Auto every 3–5 sessions** or when CLAUDE.md >80 lines / routing table >20 entries. Append to `~/.claude/suggestions.md`, never implement without approval. |
| `index` | Match task keywords to `~/.claude/manifest.json` tags → load only relevant skill files. Use at task start to avoid speculative full-skill loads. |
| `qa-agent` | "qa", "scan project", "best practices for X", "what worked/failed". Query KB before unfamiliar library work. |
| `improve` | "show improvement queue", "what should I fix", "show digest", "run daily digest", "brainstorm improvements" |
| `research-colony` | "show research digest", "what's new in AI", "any new papers", "run research colony", "fetch research" |
| `paper-dive` | `/paper-dive`, drop a PDF path or paper URL, "walk me through this paper", "help me understand this" |
| `route` | "which profile should I use", "should I use haiku", "route this task", "which model is best for" |

Skills invokable as slash commands: `/tdd`, `/diagnose`, `/zoom-out`, etc.

## Lexicon

Load `~/.claude/lexicon.md` every session. Apply defined terms without explanation. Add new terms mid-session via `Edit ~/.claude/lexicon.md`.

## Development Defaults

Always active for dev work (writing or modifying code): `tdd` + `grill-with-docs`. Off with "skip tdd" / "skip grill" / "no tests".

## Architecture Review Queue

`~/.claude/suggestions.md` = pending queue (fed by the `architecture-review` skill). Check every session; surface count only ("N suggestions pending"). Never implement without explicit approval.

## Session Start

1. Check `~/.claude/handoffs/` — if ≤7 days old, read silently and restore context
2. Check `~/.claude/suggestions.md` — mention count if pending
3. Load `~/.claude/lexicon.md`
4. Check `~/.claude/improvement-queue.md` — mention count of queued items if file exists ("N improvements queued")
5. Check `~/.claude/daily-digest/` — if today's digest exists, mention it ("today's digest ready — ask to see it")
6. Check `~/.claude/research-digest/` — if today's research digest exists, mention it ("research digest ready — N items found")
7. **Auto-route**: if the first user message clearly signals a specific task type (≥2 routing keywords), surface one routing suggestion — only once, only at session start:
   - recall/memory → "This looks like a **recall** task — `claude-recall` (marvin + haiku) handles it at ~60% of this session's cost."
   - coding (no recall) → "This looks like a **coding** task — `claude-code` (lean + sonnet) saves ~9% tokens."
   - research/paper → "This looks like a **research** task — `claude-research` (marvin + haiku) is ~60% cheaper for synthesis."
   - architecture/design/mixed → current profile is correct, say nothing.
   Routing keywords: recall="recall,remember,from memory,last session,bench result,we built"; coding="fix,implement,debug,bug,error,refactor"; research="research,paper,arxiv,summarize,what is".

## Context Switch Protocol

Before a significant topic or project change: run `handoff`, surface the resume prompt, then proceed. Triggers: different project, major topic shift, or any moment where a fresh model would clearly do better.

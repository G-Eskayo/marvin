# Claude Code Global Settings

## Agent Skills (mattpocock/skills)

Skills are installed at `~/.agents/skills/`. Auto-invoke the appropriate skill by reading its `SKILL.md` and any referenced files in the same directory when the user's request matches the triggers below.

When invoking a skill, read `~/.agents/skills/<name>/SKILL.md` first, then follow its instructions. Read any additional files it references (e.g. `tests.md`, `mocking.md`) as needed.

### Skill Routing Table

| Skill | Trigger |
|-------|---------|
| `diagnose` | Bug reported, "debug/diagnose this", broken/throwing/failing, perf regression |
| `tdd` | "TDD", "red-green-refactor", test-first development, integration tests |
| `grill-me` | "Grill me", stress-test a plan, challenge my design |
| `grill-with-docs` | Stress-test plan against project docs, sharpen terminology, update ADRs |
| `zoom-out` | Unfamiliar with code area, need higher-level architectural map |
| `improve-codebase-architecture` | Improve architecture, refactor, reduce coupling, increase testability |
| `prototype` | Prototype, mock up UI, "try a few designs", "let me play with it" |
| `handoff` | **Auto before context switch.** Topic shift, long conversation, unit of work done, new project. Save to `~/.claude/handoffs/`. |
| `caveman` | "Caveman mode", "less tokens", "be brief", `/caveman` |
| `write-a-skill` | "Create/write a new skill" |
| `setup-matt-pocock-skills` | First use in new repo before triage/tdd/diagnose/zoom-out. Activates: triage, to-issues, to-prd. |
| `self-improve` | **Auto after every non-trivial task.** Pattern observed → quality filter → create/update skill → wire. |
| `research` | Research topic, investigate claim, evaluate technology or theory |
| `creative` | Creative work, ideation, "be creative", "surprise me" |
| `lexicon` | New concept crystallises, term recurs with stable meaning, "add to lexicon" |
| `self-optimize` | **Auto every 3–5 sessions.** Review agent system. Queue suggestions. Never implements without approval. |
| `index` | Match task keywords to manifest tags → load only relevant files. Use at start of any task to identify which context boxes to open. |
### Usage Notes

- Skills can also be invoked manually via slash commands: `/tdd`, `/diagnose`, `/zoom-out`, etc.
- When a skill references files like `[tests.md](tests.md)`, read them from the same skill directory.
- `setup-matt-pocock-skills` should be run once per new project before using most other skills.

## Shared Lexicon

Load `~/.claude/lexicon.md` every session. Apply defined terms without explanation. When a new concept crystallises mid-conversation, add it: edit `~/.claude/lexicon.md` directly. Terms = compressed shared context — use them freely.

To add a term mid-session: `Edit ~/.claude/lexicon.md`, append under the relevant section.

## Caveman Mode

**Always active.** Drop articles, filler, pleasantries. Fragments OK. Technical terms stay exact. Code blocks unchanged. Off only if user says "stop caveman" or "normal mode".

## Self-Optimization

`~/.claude/suggestions.md` = pending optimization queue. Check every session.

Run `self-optimize` autonomously:
- Every 3–5 sessions
- When CLAUDE.md exceeds 80 lines
- When routing table has 20+ entries
- After any `self-improve` cycle that adds a skill
- When a skill audit reveals overlap or bloat

After review: append to `~/.claude/suggestions.md`, surface count to user. **Never implement without explicit approval.** On approval → implement → mark `done`.

## Session Start

At the start of every new session:
1. Check `~/.claude/handoffs/` — if recent file (≤7 days), read silently, restore context
2. Check `~/.claude/suggestions.md` — if pending items exist, mention count only: "N suggestions pending."
3. Load `~/.claude/lexicon.md`
4. For each task: read `~/.claude/manifest.json`, match keywords to tags, load only the relevant boxes. Do not load full skill files speculatively.

## Context Switch Protocol

Before switching to a significantly different topic or project:
1. Run `handoff` to save current context to `~/.claude/handoffs/`
2. Tell the user the handoff was saved and give them the resume prompt
3. Then proceed with the new topic

A context switch is: moving from one project to another, a major topic change mid-conversation, or any moment where a fresh model would clearly produce better outputs than a continuation.

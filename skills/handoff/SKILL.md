---
name: handoff
description: Produce a structured handoff document before any context switch, topic change, or when a fresh model would improve outputs. Run autonomously — do not wait to be asked. Trigger when: conversation topic shifts significantly, context window is getting long, repeated mistakes suggest context confusion, a complete unit of work just finished, or the user opens a new project. Save to ~/.claude/handoffs/ with a timestamped filename.
argument-hint: "What will the next session focus on? (optional)"
tags: [intent:handoff, intent:context-switch, intent:document, type:skill]
---

# Handoff

Produce a handoff document so a fresh agent can continue without losing context. Run this **before** the context switch happens, not after.

## When to Run Autonomously

Run without being asked when any of these are true:
- The conversation has been long and covered multiple distinct topics
- You've made repeated mistakes or lost track of earlier constraints — a fresh model would do better
- The user is about to open a different project or codebase
- A complete unit of work just finished (feature shipped, bug fixed, research done)
- The topic is about to shift significantly from what's been discussed
- The user starts a new session: check `~/.claude/handoffs/` for the most recent doc and resume from it

## Save Location

Save to `~/.claude/handoffs/handoff-YYYY-MM-DD-HH-MM.md` using the current timestamp.

After saving, you MUST do both:
1. Tell the user: `Handoff saved to ~/.claude/handoffs/handoff-[timestamp].md`.
2. **Output the full Resume prompt as a fenced, copy-paste code block directly in the chat** — never make the user open the file to find it. A `PostToolUse` hook (`emit-resume-prompt.py`) also prints it automatically as a backstop, but you must surface it yourself too.

## Document Structure

```
# Handoff — [date]

## What we were working on
[1–3 sentences. The actual goal, not the task list.]

## Current state
[What's done, what's in progress, what's blocked. Be specific — file paths, function names, error messages.]

## Key decisions made
[Decisions and the reasoning behind them. What was tried and rejected, and why.]

## Open questions / next steps
[What needs to happen next. Ordered by priority.]

## Suggested skills
[Which mattpocock/skills the next agent should invoke, and when.]

## Resume prompt
---
Continue from handoff: ~/.claude/handoffs/handoff-[timestamp].md

[2–3 sentence summary the user can paste at the start of a new session to orient the fresh model instantly]
---
```

## Rules

- Do not duplicate content already in files, commits, or PRDs — reference by path instead
- Redact API keys, passwords, PII
- The resume prompt must be self-contained — the next agent should be able to read it cold and know exactly where to start
- If the user passed an argument describing the next session's focus, tailor the next steps and suggested skills sections to that goal
- Keep the whole document under 150 lines — compress aggressively, reference don't repeat

## On Resume

When starting a new session, check `~/.claude/handoffs/` for the most recent file. If one exists and is recent (within 7 days), read it and use it to restore context before doing anything else.

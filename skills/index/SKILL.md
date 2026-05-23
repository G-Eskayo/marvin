---
name: index
description: Context retrieval using the manifest index. Pull only the files relevant to the current task — no full context load. Use at the start of any task to identify which boxes to open. Consult ~/.claude/manifest.json to match task keywords to tags, then read only those files.
tags: [intent:retrieve, intent:index, intent:load, type:skill]
---

# Index — Pull the Right Boxes

`~/.claude/manifest.json` is the unified index for all skills AND knowledge files.
Each entry has `name`, `path`, `tags[]`, and optionally `calls[]`.
Tags use `namespace:value` format — `domain:`, `intent:`, `type:`.

Pull exactly the boxes the task needs. Nothing else.

## Pattern

1. **Read the request** — extract 2–4 keywords describing the task
2. **Read `~/.claude/manifest.json`** — scan the `index[]` array
3. **Collect entries** whose `tags` intersect the task keywords
4. **Load those files** — read each matched `path`
5. **Check `calls`** — if a loaded skill declares `calls: [x, y]`, load those too if the task needs them
6. **Proceed** with only what's relevant

## Tag Namespaces

| Namespace | Meaning | Examples |
|-----------|---------|---------|
| `domain:` | Subject area | `domain:mcp`, `domain:debugging`, `domain:testing` |
| `intent:` | What you're doing | `intent:build`, `intent:debug`, `intent:plan` |
| `type:` | Kind of file | `type:skill`, `type:knowledge`, `type:memory-user` |

## Examples

**"There's a bug in the auth middleware"**
Keywords: debug, fix → match `intent:debug`, `intent:fix`
Load: diagnose skill
Also check: `domain:auth` entries → reference_mcp.md if MCP-related

**"Let's TDD the payment feature"**
Keywords: tdd, test, build → match `domain:testing`, `intent:tdd`, `intent:build`
Load: tdd skill (which calls: [diagnose] if needed)

**"Help me build an MCP server"**
Keywords: build, mcp → match `domain:mcp`, `intent:build`
Load: reference_mcp.md (knowledge) + research/build skills

## Manifest Structure

```
always          — loaded every session (CLAUDE.md, lexicon.md)
on_session_start — checked at session start (handoffs, suggestions)
index[]         — flat array of all tagged entries:
  name          — identifier
  path          — file to read (~ = home)
  tags          — namespaced tag array
  calls         — (optional) other skills this one may invoke
```

## Keeping the Manifest Current

Manifest is **auto-generated** from frontmatter. Do not edit it by hand.

When creating a new skill or memory file:
1. Add `tags: [namespace:value, ...]` to its frontmatter
2. Add `calls: [skill-name, ...]` if it depends on other skills
3. The PostToolUse hook runs `rebuild-manifest.py` automatically

To rebuild manually:
```
python3 ~/.agents/skills/self-improve/scripts/rebuild-manifest.py
```

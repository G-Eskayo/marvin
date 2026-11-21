---
name: write-a-skill
description: Create new agent skills with proper structure, progressive disclosure, and bundled resources. Use when user wants to create, write, or build a new skill.
tags: [intent:create, intent:skill, intent:codify, type:skill]
---

# Writing Skills

## Process

1. **Gather requirements** - ask user about:
   - What task/domain does the skill cover?
   - What specific use cases should it handle?
   - Does it need executable scripts or just instructions?
   - Any reference materials to include?

2. **Draft the skill** - create:
   - SKILL.md with concise instructions
   - Additional reference files if content exceeds 500 lines
   - Utility scripts if deterministic operations needed

3. **Review with user** - present draft and ask:
   - Does this cover your use cases?
   - Anything missing or unclear?
   - Should any section be more/less detailed?

## Skill Structure

```
skill-name/
├── SKILL.md           # Main instructions (required)
├── REFERENCE.md       # Detailed docs (if needed)
├── EXAMPLES.md        # Usage examples (if needed)
└── scripts/           # Utility scripts (if needed)
    └── helper.js
```

## Template and Format

Template, frontmatter fields and description rules: see [REFERENCE.md](REFERENCE.md). The description is the only thing the agent sees when choosing a skill: say what it does, then 'Use when ...' triggers, max 1024 chars.

## When to Add Scripts

Add utility scripts when:

- Operation is deterministic (validation, formatting)
- Same code would be generated repeatedly
- Errors need explicit handling

Scripts save tokens and improve reliability vs generated code.

## When to Split Files

Split into separate files when:

- SKILL.md exceeds 100 lines
- Content has distinct domains (finance vs sales schemas)
- Advanced features are rarely needed

## Review Checklist

After drafting, verify:

- [ ] Description includes triggers ("Use when...")
- [ ] SKILL.md under 100 lines
- [ ] Frontmatter includes at least `name`, `description`, `tags` (required), and `model-scope` if needed
- [ ] No time-sensitive info
- [ ] Consistent terminology
- [ ] Concrete examples included
- [ ] References one level deep
- [ ] If the skill claims to "run automatically" / "no user prompt needed": is there a real enforcement mechanism (hook, cron, log) behind that claim, not just the description asserting it? Confirmed 2026-07-03 — `self-improve`'s own autonomy claim went unexercised for weeks until a PostToolUse hook was actually wired in; the prose alone never fired it.
- [ ] If skill requires a specific model tier: set `model-scope` with evidence (e.g., bench run showing degradation)

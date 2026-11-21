# write-a-skill Reference

## SKILL.md Template

```md
---
name: skill-name
description: Brief description of capability. Use when [specific triggers].
tags: [type:skill, intent:..., domain:...]
model-scope: all
---

# Skill Name

## Quick start

[Minimal working example]

## Workflows

[Step-by-step processes with checklists for complex tasks]

## Advanced features

[Link to separate files: See [REFERENCE.md](REFERENCE.md)]
```

**Frontmatter fields**:
- `name`: short kebab-case identifier
- `description`: agent-facing trigger text (max 1024 chars)
- `tags`: [required] at least one tag; use `type:skill`, plus domain/intent tags
- `model-scope`: [optional] model tier restrictions (omit or `all` for unrestricted; `sonnet+` for sonnet and above; `haiku,sonnet` for comma-separated list)

## Description Requirements

The description is **the only thing your agent sees** when deciding which skill to load. It's surfaced in the system prompt alongside all other installed skills. Your agent reads these descriptions and picks the relevant skill based on the user's request.

**Goal**: Give your agent just enough info to know:

1. What capability this skill provides
2. When/why to trigger it (specific keywords, contexts, file types)

**Format**:

- Max 1024 chars
- Write in third person
- First sentence: what it does
- Second sentence: "Use when [specific triggers]"

**Good example**:

```
Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when user mentions PDFs, forms, or document extraction.
```

**Bad example**:

```
Helps with documents.
```

The bad example gives your agent no way to distinguish this from other document skills.

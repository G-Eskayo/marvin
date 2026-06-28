---
name: diagnose-to-improve
description: Failure investigation that feeds back into durable skill improvements. Triggers when something breaks, a dead end is hit, or an approach repeatedly fails.
tags: [scenario:debug-to-improve, intent:debug, intent:improve, domain:debugging, type:scenario]
calls: [diagnose, self-improve]
---

# Scenario: Diagnose → Improve

## When to use

- Something broke and root cause is unclear
- Same failure hit twice — pattern worth codifying
- An approach failed and the path taken should be recorded to avoid repetition

## Skill sequence

```
diagnose          ← isolate root cause, confirm fix
     ↓
self-improve      ← ISF: F entry (what failed + path taken), I entry if fix is generalizable
```

## Handoff points

| Between | What to carry forward |
|---------|----------------------|
| diagnose → self-improve | Root cause, failed approaches tried, fix applied |

## Failure modes

- **Fixing without annotating**: same failure recurs next session, no F entry in retrospective
- **Annotating without qualifying**: noise in retrospective — only annotate if failure is likely to recur in different contexts

## Known companions

`research` — if root cause requires external domain knowledge  
`grill-me` — if the fix involves an architectural decision  
`write-a-skill` — if the fix reveals a reusable pattern worth a full skill

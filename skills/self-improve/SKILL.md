---
name: self-improve
description: Meta-skill that runs autonomously after every non-trivial task — no user prompt needed. Observes patterns, failures, and recurring approaches, then creates or updates skills that pass a 3-gate quality filter (recurrence, evidence, value). Auto-wires new skills into commands and routing table via wire-skill.sh.
tags: [intent:improve, intent:learn, intent:codify, intent:meta, type:skill]
calls: [lexicon, write-a-skill]
---

# Self-Improve

A disciplined loop for turning observed patterns into durable skills — without codifying noise.

## When to Trigger

**This skill runs autonomously — do not wait to be asked.**

Run after every non-trivial task. Specifically, always run after:
- Completing a complex or multi-step task
- A `diagnose`, `tdd`, `research`, or `creative` session ends
- Struggling or failing at something before finding a solution
- Using the same approach that worked well in a prior context
- Encountering a gap where no existing skill applied

The user does not need to say anything. Self-improvement is a background responsibility, not a user-facing command.

Do NOT create a skill when:
- The pattern is too context-specific to generalize
- It only applies to this exact file, repo, or conversation
- The approach is unverified (one success ≠ a pattern)
- See [quality-filter.md](quality-filter.md) for the full gate criteria

## Process

### 1. Identify the pattern

State clearly:
- What task type or situation triggered this
- What the reusable insight or approach is
- How many times this has come up (or strong prediction it will)

### 2. Apply the quality filter

Read [quality-filter.md](quality-filter.md). A new skill must pass all three gates:
- **Recurrence gate**: will this come up again in different contexts?
- **Evidence gate**: is the approach grounded, not just convenient?
- **Value gate**: does codifying this meaningfully improve outcomes?

If it fails any gate, write a brief note on why and stop. Not every pattern is worth locking in.

### 3. Draft or update the skill

**New skill**: follow [write-a-skill](../write-a-skill/SKILL.md) process.
- Place in `~/.agents/skills/<skill-name>/`
- Keep SKILL.md under 100 lines; split supporting content into separate files
- Description must include specific trigger phrases

**Updating existing skill**: read the current SKILL.md, identify what's wrong or missing, make targeted edits. Don't rewrite what works.

### 4. Auto-wire the skill

Run the wiring script to symlink the new skill and add it to the routing table:

```bash
~/.agents/skills/self-improve/scripts/wire-skill.sh <skill-name> "<trigger description>"
```

This:
- Symlinks `~/.agents/skills/<skill-name>/SKILL.md` → `~/.claude/commands/<skill-name>.md`
- Appends the skill to the routing table in `~/.claude/CLAUDE.md`

### 5. Validate

- Read the newly wired skill back to confirm it makes sense
- Check the CLAUDE.md routing table entry is accurate
- If updating: confirm the change addresses the failure without breaking existing use cases

## Domains

This skill applies to improvements across four capability areas:

| Domain | What to improve |
|--------|----------------|
| **Development** | Coding patterns, debugging loops, architecture heuristics |
| **Creative** | Approaches that escape safe/generic outputs |
| **Research** | Source triangulation, confidence tiering, epistemic hygiene |
| **Truth-seeking** | Reasoning under uncertainty, theory evaluation, bias detection |

## Epistemic Stance

Skills encode working hypotheses, not truths. When writing a skill:
- State what the approach is optimized for
- Note known limitations or when it breaks down
- Prefer "works well when X" over universal claims
- A skill that says "always do Y" is almost always wrong

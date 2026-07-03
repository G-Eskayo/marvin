---
name: self-improve
description: Meta-skill that runs autonomously after every non-trivial task — no user prompt needed. Observes patterns, failures, and recurring approaches, then creates or updates skills that pass a 3-gate quality filter (recurrence, evidence, value). Auto-wires new skills into commands and routing table directly (Write + Edit, no script).
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

## ISF Annotation Framework

Every self-improve run **must** classify what it observed into one or more of these three categories before proceeding:

| Category | What it captures | Purpose |
|----------|-----------------|---------|
| **I — Improve** | New pattern or approach discovered; what changed and how it was achieved | Encode the gain so it compounds |
| **S — Sustain** | What succeeded and why; how to repeat it reliably | Prevent regression; don't lose what works |
| **F — Failure** | Where it failed, what roadblock was hit, what path was taken | Avoid repeating; short-circuit dead ends |

Write the ISF annotation first, before drafting or updating any skill. If you cannot classify the observation into at least one category, it is not worth codifying.

**Annotation format** (append to the relevant skill's `retrospective.md`, creating it if absent):

```markdown
## YYYY-MM-DD — <task or context>
**I:** <what improved and how>  
**S:** <what worked and how to repeat it>  
**F:** <what failed, the roadblock, the path taken>
```

Omit any line that has nothing to say. At least one line must be present.

Also append a one-line summary to `~/.agents/retrospective-log.md` (cross-skill pattern index):
```
YYYY-MM-DD | <skill-name> | I/S/F | <one-line summary>
```

---

## Process

### 1. Identify the pattern

Apply the ISF framework above. Then state clearly:
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

No script for this — `~/.claude/commands/*.md` files are plain content files, not symlinks (verified against every existing one). Do both directly:

1. Write `~/.claude/commands/<skill-name>.md` with exactly this template:
   ```
   Invoke the <skill-name> skill. Read `~/.agents/skills/<skill-name>/SKILL.md` and follow its protocol.

   $ARGUMENTS
   ```
2. Edit `~/.claude/CLAUDE.md`'s routing table to append a row for the new skill.

(This step used to point at `scripts/wire-skill.sh` — that file never existed. Caught 2026-07-03 while building the background reviewer below.)

### 5. Validate

- Read the newly wired skill back to confirm it makes sense
- Check the CLAUDE.md routing table entry is accurate
- If updating: confirm the change addresses the failure without breaking existing use cases

## Skill Co-occurrence Patterns

After each multi-skill session, check: did two or more skills fire in sequence? If yes:
- Does a scenario file already exist in `~/.agents/scenarios/` for this combination?
- If yes: does the session confirm, extend, or contradict it? Update accordingly.
- If no and the combination recurred or is clearly likely to recur: create a new scenario file.

Scenario file format: trigger, skill sequence with arrows, handoff points table, failure modes, known companions.

This is how the system learns its own workflow patterns — not from prescription but from observed use.

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

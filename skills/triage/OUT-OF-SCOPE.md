# The `.out-of-scope/` Knowledge Base

When an enhancement is triaged as `wontfix`, the reasoning shouldn't just close the issue and
evaporate — it goes in `.out-of-scope/` so the next time someone (or some agent) proposes the
same or a similar idea, triage can surface the prior decision instead of re-litigating it from
scratch.

## Structure

One file per rejected idea: `.out-of-scope/<slug>.md`

```markdown
# [Idea title]

**Rejected**: YYYY-MM-DD
**Original issue**: #[number]

## What was proposed

[the enhancement, stated plainly — enough that a future reader recognizes "oh, this is the same
thing" without needing to reread the original issue]

## Why it was rejected

[the actual reasoning — not "not a priority" but the real load-bearing reason: conflicts with an
architectural decision, was tried before and didn't work, out of scope for the project's actual
goals, etc.]

## What would change this

[if there's a condition under which this would be reconsidered — a future milestone, a changed
constraint — state it. If genuinely permanent, say so.]
```

## Consumer rules

- **Before triaging any enhancement**, grep `.out-of-scope/` for anything resembling the current
  proposal — triage SKILL.md step 1 already requires this. Surface a match to the maintainer
  before proceeding, even if they end up deciding to revisit it.
- **Only write a real, load-bearing reason.** "Not a priority right now" isn't durable — it'll
  look wrong in six months when priorities shift. If the actual reason is just "not prioritized,"
  that's arguably not a true `wontfix` at all — flag it to the maintainer rather than writing a
  thin entry.
- **Link from the closing comment** on the original issue to the `.out-of-scope/<slug>.md` file,
  so the paper trail is navigable in both directions.

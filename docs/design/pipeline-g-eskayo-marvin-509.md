This confirms the HITL/AFK split is an established, load-bearing pattern (`to-issues`'s tracer-bullet breakdown) that the ticket pipeline itself relies on — nothing new being invented. Now writing the plan.

## North-star fit

Reuses the existing pattern verbatim: `skills/to-issues/SKILL.md`'s own `Type: HITL / AFK` field (step 4, line 51) and its quiz question "Are the correct slices marked as HITL and AFK?" (line 60). `to-tasklist/SKILL.md` already declares itself a sibling of `to-issues` with the same tracer-bullet discipline and already runs the HITL/AFK self-check in step 1 and claims its quiz is "Same as `to-issues` step 4" (line 24) — the template in step 3 is simply missing the field that quiz question is about. This is the simplest sufficient fix: three single-line additions to one file, no new mechanism, no schema, no code. It spends essentially no tokens (a doc edit) and saves tokens/time later: per CONTEXT.md, `to-issues`'s HITL/AFK breakdown is already load-bearing for the MR ticket pipeline, and `to-tasklist` exists precisely for projects with no tracker and no session-scoped task tool, where the file *is* the only durable record across session/machine boundaries (north star 2 — phone OS: a resumed task list should say unassisted which tasks can run unattended). Leaves the user (a future resuming agent or Gil) more capable: it removes a silent gap where a judgment already made (HITL vs AFK) is lost and must be re-derived by re-reading a stale conversation. No north star argues against this.

## Decisions

None — the ticket is fully specified (exact template line, exact quiz question text, exact step-4 wording), has `ready-for-agent`, and is docs-only with no owner choice required.

## Tests (docs-only — exempt per ticket's "How we'll try to break it")

The ticket explicitly marks this exempt, and that's correct: this change touches no code path, so there's no behavior to write a test against. Verification here is a manual content check against the three acceptance criteria below, confirmed by re-reading the edited file after each change (verify fails if the file changes without the corresponding criterion line present).

## Task List

- [ ] T1 — In `skills/to-tasklist/SKILL.md` step 3's template (line 26-34 block), add `Type: HITL | AFK` as a new line immediately after `Blocked by: <task id(s) or "none">` (before the description line), mirroring `to-issues/SKILL.md`'s own `**Type**: HITL / AFK` field.
- [ ] T2 — In step 2 (line 24), append "Are the correct tasks marked HITL and AFK?" to the quiz bullet, alongside the existing granularity/dependency-order confirmation, mirroring `to-issues/SKILL.md` line 60's wording ("Are the correct slices marked as HITL and AFK?") adapted to "tasks."
- [ ] T3 — In step 4 (line 36), add a clause noting that `Type:` can be corrected in place if the initial marking was wrong, the same way the checkbox is updated in place.
- [ ] T4 — Re-read the edited file and confirm all three acceptance criteria are literally satisfied (the `Type: HITL | AFK` line exists in the step-3 template, the HITL/AFK question exists in step 2, step 4 mentions correcting `Type:` in place).
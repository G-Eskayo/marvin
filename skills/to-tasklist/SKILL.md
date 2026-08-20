---
name: to-tasklist
description: Convert a confirmed design/requirements doc into a persisted markdown task list with per-task status checkboxes, for projects that have no issue tracker (private/local-only repos). Use when a design doc has just been approved and the project has no GitHub issues (e.g. local-only git repos holding sensitive data), instead of to-issues/to-prd.
tags: [intent:plan, intent:tasks, intent:breakdown, type:skill]
calls: [to-issues]
---

# To Tasklist

Sibling of `to-issues`, for projects that structurally can't have a tracker — same tracer-bullet discipline, different output: a durable file instead of a tool call.

## When to use this instead of to-issues/to-prd

`to-issues` and `to-prd` both publish to a GitHub-style issue tracker and require one to exist. Some projects never will have one (e.g. `finance-os`: local-only git, holds real financial data, no public repo — see project memory). For those, don't fall back to the session-scoped `TaskCreate`/`TaskList` tools either — that state doesn't survive a session boundary or a machine switch, which defeats the point of finishing a design (being ready to execute *whenever* work resumes, not just this session).

Check for a real tracker first (git repo + triage labels, per `setup-matt-pocock-skills`). If one exists, use `to-issues` instead. Only use this skill when there is none.

## Process

1. **Draft vertical slices** — same tracer-bullet rules as `to-issues`: each task is a thin, end-to-end, independently-completable slice, not a horizontal layer. Group into tracks when the work spans multiple systems (e.g. a track per repo/component touched).

2. **Quiz the user** — present the numbered breakdown, confirm granularity and dependency order, iterate until approved. Same as `to-issues` step 4.

3. **Write the task list file** — save as `<design-doc-name>-tasks.md` next to the design doc it was derived from (e.g. `docs/features/foo.md` → `docs/features/foo-tasks.md`). Use this format per task:

   ```md
   ## Track: <track name>

   - [ ] **T1** — <short title>
     Blocked by: <task id(s) or "none">
     <1-3 sentence description of the end-to-end slice>
   ```

4. **Update the checkbox in place** as work on a task starts/completes — this file is the source of truth for status, not the conversation that produced it. Point any resume/handoff prompt at this file rather than restating task state in prose.

5. **Reflect the plan in the project roadmap** if one exists (e.g. `~/.claude/marvin-roadmap.md`), so it's discoverable outside the project directory too.

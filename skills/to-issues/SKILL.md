---
name: to-issues
description: Break a plan, spec, or PRD into independently-grabbable issues on the project issue tracker using tracer-bullet vertical slices. Use when user wants to convert a plan into issues, create implementation tickets, or break down work into issues.
tags: [intent:plan, intent:issues, intent:breakdown, type:skill]
---

# To Issues

Break a plan into independently-grabbable issues using vertical slices (tracer bullets).

The issue tracker and triage label vocabulary should have been provided to you — run `/setup-matt-pocock-skills` if not.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes an issue reference (issue number, URL, or path) as an argument, fetch it from the issue tracker and read its full body and comments.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Issue titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

### 3. Draft vertical slices

Break the plan into **tracer bullet** issues. Each issue is a thin vertical slice that cuts through ALL integration layers end-to-end, NOT a horizontal slice of one layer.

Slices may be 'HITL' or 'AFK'. HITL slices require human interaction, such as an architectural decision or a design review. AFK slices can be implemented and merged without human interaction. Prefer AFK over HITL where possible.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Prefer many thin slices over few thick ones
</vertical-slice-rules>

**Self-check granularity before quizzing the user** (same bar `triage` applies before invoking this skill — check it here too, since this skill also runs standalone against a plan/PRD with no triage pass first). A drafted slice is too coarse if any of these hold:
- More than ~4-5 independently-checkable acceptance criteria
- Acceptance criteria span more than one subsystem/file-area
- The slice mixes a HITL decision (something needing the maintainer's judgment) with AFK implementation work

Split any slice matching one of these before presenting the list in step 4 — don't rely on the user's own "too coarse?" answer to catch what a fixed criterion already would have.

**AFK slices must land in the repo the ticket is filed in.** The ticket pipeline judges a run by measuring *that* repo's tests. If the work actually lives in a different repo (a website, a companion app, a new repo that doesn't exist yet), every run measures "unchanged" and the ticket fails or gets parked even when the agent did the work. clarity-captions #44 (its website) was parked for exactly this reason. Either file the slice in the repo where the code will live, or mark it HITL.

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name
- **Type**: HITL / AFK
- **Blocked by**: which other slices (if any) must complete first
- **User stories covered**: which user stories this addresses (if the source material has them)

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?
- Are the correct slices marked as HITL and AFK?

Iterate until the user approves the breakdown.

### 5. Publish the issues to the issue tracker

For each approved slice, publish a new issue to the issue tracker. Use the issue body template below. These issues are considered ready for AFK agents, so publish them with the correct triage label unless instructed otherwise.

Publish issues in dependency order (blockers first) so you can reference real issue identifiers in the "Blocked by" field.

<issue-template>
## Parent

A reference to the parent issue on the issue tracker (if the source was an existing issue, otherwise omit this section).

## What to build

A concise description of this vertical slice. Describe the end-to-end behavior, not layer-by-layer implementation.

Avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it here and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.

## North-star fit

Short, against `docs/north-stars.md` (MARVIN repo): what it reuses before adding anything, why it's the simplest sufficient approach, where it saves or spends tokens, what it does for the phone-OS direction, and whether it leaves the user more capable or just more passive. If a north star argues against the slice, say so. Scaffolding other work will build on gets the `foundation` label.

## Purpose metric

Only when the slice's purpose is measurable (faster, fewer tokens, fewer refusals): name a measure registered in `lib/purpose_metrics.py` (add one there if none fits; a ticket never supplies a command), with a baseline you measured, a target and a date to check. Add the `purpose-metric` label. The daily outcome check measures it after that date and comments the result; a miss gets a missed-purpose diagnosis and turns Health red.

- **Measure:** headless-refusal-rate
- **Baseline:** 14.3
- **Target:** -70%
- **Check on:** 2026-10-16

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Blocked by

- A reference to the blocking ticket (if any)

Or "None - can start immediately" if no blockers.

## Docs

- The docs this slice depends on or will change: write ADRs as "ADR 0033", and name `CONTEXT.md` or `README.md` when they apply. The dashboard turns these into live links in both directions (ticket <-> doc), so a reader of the ticket can open the doc and a reader of the doc can see every ticket that points at it.

Or "None" if it touches no documented decision.

</issue-template>

Do NOT close or modify any parent issue.

### 6. Make sure the project has a dashboard board

After publishing, run `~/.agents/venv/bin/python ~/.agents/lib/board_registry.py ensure <owner/repo>` (add `--due YYYY-MM-DD --hard` if the project has a fixed deadline). It is idempotent; the Activity tab's per-project board then shows these tickets by column (backlog, ready, blocked, in progress, in review/testing, done) with PR links. Never store tickets in the registry -- the board reads them live from the tracker.

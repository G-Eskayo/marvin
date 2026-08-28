# 0029 — Per-ticket design docs and task lists live in the PR, not written direct to CONTEXT.md/ADRs

## Status

Accepted (2026-08-28)

## Context

`sandbox_orchestration._default_executor`'s planning phase today produces a throwaway prose plan
(a string, piped straight into the Haiku execution prompt) — never persisted, never independently
reviewable, no real task breakdown. Gil wants this upgraded to a real artifact trail: evaluate the
ticket, read the current state of the files it touches, produce a real design doc, derive a real
task list from it, then execute against that task list — closing the gap issue #69 ("Automated
design-doc pipeline — 'design the designing'," filed as a research-spike, unresolved) asked about
in the abstract, now scoped concretely to `ready-for-agent` tickets.

The open question this ADR resolves: once the pipeline is producing real design docs
autonomously, where do they live — written directly into `CONTEXT.md`/`docs/adr/` the way a live
grill-with-docs session does it (this session included), or committed as files inside the ticket's
own worktree/PR?

## Decision

**Files inside the ticket's own worktree, committed as part of its branch — reviewed by the exact
same merge-time gates as the code** (rebase/retest, code-review, qa-agent's judged pass, [[0026]]/
[[0027]]). They do not become real `CONTEXT.md`/ADR content automatically. A PR merging does not by
itself update the domain glossary or decision log — that stays a human (or a live grilling
session) folding in whatever from the merged design doc is actually worth keeping, same as today.

## Consequences

- Autonomous design docs get the same scrutiny as autonomous code — one trust boundary (the PR),
  not two. No new review surface to build or maintain.
- `CONTEXT.md`/`docs/adr/` stay curated, not auto-populated — avoids drift from a design doc that
  was good enough to pass the merge gates but wasn't actually worth promoting to permanent
  glossary/decision-log status.
- Real gap, not resolved here: nothing currently folds a merged ticket's design doc back into
  `CONTEXT.md`/`docs/adr/` even when it *should* be promoted — that stays a fully manual, easy-to-
  forget step. Worth a future thread if this turns out to lose real decisions.

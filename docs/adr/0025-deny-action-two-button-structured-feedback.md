# 0025 — Deny action: two dashboard buttons, structured-feedback modal, not a third "adjust" button

## Status

Accepted (2026-08-27)

## Context

Issue #1 (parent PRD) flagged deny/adjust as unresolved: "deny plausibly closes the PR/ticket with
a comment (mechanical); adjust plausibly means leaving PR review comments that a later background
pass picks up to re-engage the sandbox loop" — explicitly not designed, connected to the
still-unscoped "SCRUM master" re-engagement idea.

Gil's direction when this came up again (reviewing #71 live): merge the two into one Deny action
rather than building three dashboard buttons (approve/deny/adjust), and instead stand up a
separate, distinct future system — a "review, debug, and improve" pipeline — that consumes denied
PRs and attempts re-engagement. The dashboard's own surface area should stay Approve/Deny; the
re-engagement mechanism itself is a different, larger, not-yet-designed system.

## Decision

Two dashboard buttons: **Approve** (existing, #71) and **Deny**. Deny opens a modal with
structured, standardized feedback — a set of reason categories (design/requirements mismatch,
insufficient tests, evidence missing, regression/quality) as checkboxes or a dropdown, plus an
optional free-text comment for anything the categories don't cover — and two terminal actions:

- **Send feedback**: comments the structured feedback onto the PR/ticket, releases the ticket's
  claim, and tags it for the future review/debug/improve pipeline to eventually pick up.
- **Drop entirely**: closes the PR and ticket, releases the claim, no re-engagement expected.

A placeholder GitHub issue is filed for the future review/debug/improve pipeline — title and rough
intent only, explicitly undesigned — so this thread is staked out rather than left to be
rediscovered the way the original "adjust" note almost was.

## Consequences

- The dashboard ships a real, complete two-way approve/deny decision now, without waiting on the
  undesigned re-engagement pipeline.
- "Send feedback"'s tagging mechanism (how a denied-with-feedback ticket becomes discoverable to a
  future automated pass) needs its own design once the review/debug/improve pipeline is actually
  built — this ADR only commits to the dashboard-side action and where the feedback is recorded
  (PR/ticket comment), not how anything downstream consumes it.
- Structured reason categories mean the dashboard (and eventually the re-engagement pipeline) can
  reason about *why* something was denied programmatically, not just read prose — but the category
  list itself will need revisiting once real denials start happening and the taxonomy proves too
  narrow or too broad.
- Known gap: "Drop entirely" is irreversible from the dashboard's perspective (closes PR + ticket).
  No undo/reopen flow was discussed — worth confirming before this ships if that's a real risk.

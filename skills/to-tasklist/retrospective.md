# Retrospective — to-tasklist

## 2026-08-19 — finance-os bills/calendar feature, doc-first cycle
**I:** Created `to-tasklist` as a sibling of `to-issues`/`to-prd` for projects with no issue tracker. Existing guidance (feedback-doc-first-process memory, 2026-07-13 addendum) said to fall back to session-scoped `TaskCreate`/`TaskList` when no tracker exists — this session instead persisted the task list as a checkbox markdown file in the project docs directory, which survives session/machine boundaries the way the tool-based fallback doesn't.
**S:** The design → grill/review → task-list conversion cycle completed cleanly end-to-end for the 2nd tracked instance (finance-os bills-and-payment-calendar), confirming the doc-first process itself works when followed. What changed this time is *where the task list lives*, not whether one gets made.
**F:** None this session — flagging the tool-based fallback as the weaker option came from noticing it would have lost state between sessions, not from it actually failing here.

# to-issues retrospective

## 2026-10-06 — clarity-captions ticket re-scoping (handoff-2026-10-06-22-16)
**I:** Added an AFK-slice rule: the work has to land in the repo the ticket is filed in. The pipeline measures the filing repo's tests, so cross-repo work (clarity-captions #44, website in a new repo) always reads "unchanged" and gets parked even if the agent did the work. Fix: file the slice in the target repo, or mark it HITL.
**F:** #37 (language picker) failed twice (a Swift compile error, then a mixed result) and now needs splitting. The existing granularity self-check should have flagged it at filing time. The check is already in place, so nothing new was added for it.

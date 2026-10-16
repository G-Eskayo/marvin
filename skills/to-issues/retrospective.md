# to-issues retrospective

## 2026-10-06 — clarity-captions ticket re-scoping (handoff-2026-10-06-22-16)
**I:** Added an AFK-slice rule: the work has to land in the repo the ticket is filed in. The pipeline measures the filing repo's tests, so cross-repo work (clarity-captions #44, website in a new repo) always reads "unchanged" and gets parked even if the agent did the work. Fix: file the slice in the target repo, or mark it HITL.
**F:** #37 (language picker) failed twice (a Swift compile error, then a mixed result) and now needs splitting. The existing granularity self-check should have flagged it at filing time. The check is already in place, so nothing new was added for it.

## 2026-10-15 — #358 Suggestions tab moved to an interactive build (handoff)
**I:** Added an AFK-slice rule: acceptance criteria have to be machine-checkable. #102 "Suggestions tab" was AFK but its real bar was "human readable / visually appealing". It failed 119 pipeline runs, and Gil's send-backs (10-10, 10-13) ended up reviewing unchanged code. Fix: mark taste-judged slices HITL, or split data/behaviour (AFK) from presentation (HITL).
**S:** The interactive pattern used for the boot sequence (#431, #433) worked: real-app screenshots and recordings, Gil steers through options, then adversarial tests. It's now the template for #358.
**F:** The `hold` and `ready-for-agent` labels were both on the ticket at once, so the pipeline kept picking up a held ticket. Already tracked as #455 "Honest status for held tickets", so no rule added here.

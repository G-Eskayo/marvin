1. [ ] Write `lib/tests/test_docs_vs_files_review.py` (tests 1–14 above) against the *current* (rejected) doc first, confirming each new/changed test fails for the specific reason the code review gave (e.g. test 7 fails on the old doc only because of the stale regex, not a missing section).
2. [ ] Rewrite `docs/plans/docs-vs-files-review.md`:
   - Today-state for each tab, unchanged factually from the verified table above (local-first/GitHub-fallback, uncommitted/unpushed badges, `detectKind`'s markdown/json/text-only support).
   - Overlap/gap table, with the #402 row and its own "Note on #402" paragraph both using the **single consistent sentence** about #402's scope (Files-only, new reusable component, no `Markdown.jsx` change).
   - Options A/B/C analyzed verbatim from the ticket, each with all four facets; Option C's tab-removal consequence phrased as deferred-to-follow-up everywhere it's mentioned (no fact/assumption split).
   - Recommendation naming one lettered option, reasoning that doesn't promise usage-data collection that doesn't exist (revisit on direct feedback instead).
   - The Decisions block above, embedded as its own section with id `tabs_architecture` (matching this plan).
3. [ ] Run `pytest -q lib/tests/test_docs_vs_files_review.py`, then the full suite — confirm all 14 pass against the rewritten doc and nothing else regresses.
4. [ ] Open the PR: review doc + test file are the only changes; PR body carries the Decisions block verbatim; links #403 and #402.
1. `lib/owner_decisions.py`: extract `_fresh_status`, add `pr_built_status`, add `fetch_pr` + its single-PR GraphQL query, add `status` CLI subcommand; write tests 1–6.
2. `lib/owner_decisions.py::sync()`: replace the "no longer open" close branch with the fresh re-check via `fetch_pr`; rewrite test 7, confirm test 8 (AC4) still passes.
3. New `dashboard/webhook-server/owner_decisions_gate.js` (`assertOwnerDecisionsBuilt`); write tests 9–12.
4. Wire it into `merge.js::mergePrUnqueued`'s `deps`/call sequence; write test 13.
5. Add `OWNER_DECISIONS_UNCHECKED`/`OWNER_DECISIONS_UNBUILT` to `merge_order.js::HOLD_UNTIL`; write tests 14–15.
6. Update `docs/agents/decisions-format.md`'s "After the owner answers" section and `CONTEXT.md`'s "Answers not built yet" / "Owner decisions waiting on MARVIN" bullets to describe the merge-time fresh check and the merged-PR re-check (doc-first convention, both already describe this exact mechanism).
7. Run the full Python and dashboard suites (not just the touched files) before opening the PR, per the "full suites before a hand-merge" rule — this is a merge-gate change, a regression here breaks every future merge.
8. Open the PR with the Decisions section above, naming ticket #1261 and linking the two prior failed-verification comments as context for reviewers.
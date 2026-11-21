## North-star fit

- **Reuses before adding anything new:** `board_registry.list_boards()` (`lib/board_registry.py:92`) for "every repo the board covers" instead of a hand-rolled repo list; the REST-pagination style already proven in `lib/purpose_metrics.py:465` (`_ci_onnx_download_failures`, `page += 1` loop) for the GitHub PR listing; the `"(\d+) tests? collected"` regex already validated in production by `site/scripts/facts.mjs:38` for parsing pytest's collect-only output; the point-in-time drift-probe shape already established by `lib/purpose_metrics.py:424` (`_banner_skill_count_drift`) for the new recurrence probe; `write_facts()`'s existing try/except-never-blocks-the-map skeleton (`brain-map/export_snapshot.py:275`) for the merge step. No new files.
- **Simplest sufficient approach:** `compute_facts()` stays pure (same inputs → same outputs, no I/O); a second small pure function (`merge_with_previous`) carries the "keep the last good value" rule, so the existing architecture (`compute_facts` pure / `gather` reads / `write_facts` deploys) doesn't change shape, only what `gather` reads.
- **Where it spends tokens, deliberately:** REST-paginating `/pulls?state=closed` per board repo costs more GitHub calls than the old title search, but it's explicitly kept off the GraphQL budget the pipeline lives on (ticket's own requirement), and it only runs once a day / once per `marvin` commit, not per request.
- **Leaves the user more capable:** closes a real "public numbers are wrong" gap (94/6,739 shown vs. 101/8,236 by hand) with no more hand re-counting — north star 3 as the ticket states.
- **A north star argues against part of the naive approach:** minimise-resources (north star 1) argues against running the site's actual test files (`node --test`) just to count them when a static count would be cheaper — but there's no safe "list-only" mode for Node's built-in test runner, the two site test files are 205 lines total, and `npm test` already runs them routinely, so the marginal cost is negligible and the result is exact rather than approximated. Noted, not overridden.

## A real cross-cutting constraint found while reading the current code

`lib/tests/test_instance_move.py::test_the_brain_map_facts_read_run_results_from_the_instance` (line 62) asserts facts.py's source literally contains `instance.path("bench", "metrics")`. Once `tests` stops being read from `bench/metrics/ticket-*.json` (the ticket's whole point), that assertion has nothing left to guard for this file and must be deleted, not worked around.

`lib/tests/instance_grandfathered.txt` lists `brain-map/scripts/facts.py` because its current docstring contains `"Implement G-Eskayo/<repo>#N"` — a quoted identity string the ratchet (`lib/tests/test_instance.py::test_the_grandfathered_list_only_shrinks`) flags. The ticket's required docstring rewrite removes that phrase (PR counting no longer mentions a title format), so the file stops being an "offender" and **must** come off the grandfathered list in the same commit — this check runs as a pre-commit hook, so a commit leaving the file listed won't even save.

Both are concrete, mechanical fixes, not design choices — called out here because missing either would fail the merge gate (`lib/rule_checks.py`'s `RULE_TESTS`), and a prior attempt at this ticket was already sent back once for "must-fix issues" with no detail logged.

## Tests to write first

**PR counting (`brain-map/scripts/test_facts.py`)**
1. A mocked repo with >100 closed PRs: pagination collects all of them (two pages, 100 + 5).
2. A merged PR whose head ref starts with `pipeline/` counts regardless of a hand-changed title.
3. A closed-but-unmerged PR (`merged_at` null) with a `pipeline/` head ref is not counted.
4. A non-pipeline PR titled `"Implement G-Eskayo/..."` (the old convention) is not counted — no title matching exists at all.
5. Counts sum correctly across multiple board repos.
6. One repo's `gh api` call failing (non-zero exit, or raising) fails the **whole** total to `None` — never a silently-undercounted partial sum.
7. An empty board-repo list (corrupt/missing registry) returns `None`, never `0`.
8. `gh` missing / times out → `None`, never a crash.
9. Malformed JSON from `gh api` → `None`, never a crash.

**Test counting**
10. Python collection: one file fails to collect (import error) — the rest are still counted from `"N tests collected, M errors"`, and the error is reported (stderr), never inflated or zeroed.
11. Python collection with no parseable "tests collected" line (or a literal 0) → `None`, never `0`.
12. JS (vitest): `dashboard/node_modules` missing → `None` with a reason, never `0`.
13. JS: counts non-blank lines from `npx vitest list`.
14. Site tests: `site/node_modules` missing → `None`.
15. Site tests: parses Node's TAP `# tests N` summary line.
16. `tests` (total) is written **only** when all three parts gathered this run; if one part is missing, the other parts still write individually but no partial/dishonest total is written.

**Merge-with-previous ("keep the last good value and date")**
17. A figure present in the fresh gather always wins, dated today, no `<figure>_counted_on` emitted.
18. A figure missing from the fresh gather but present in `previous` is carried forward with its value and a `<figure>_counted_on` (today's gather doesn't silently relabel a stale number as freshly counted); staleness compounds forward across multiple missed runs rather than resetting.
19. A figure absent from both stays absent — never synthesized as 0.
20. `write_facts()` reads the out_dir's existing `facts.json` before overwriting and merges (extends `brain-map/scripts/test_export_snapshot.py`).
21. No previous file (first run) → existing two tests in `test_export_snapshot.py` keep passing unchanged.
22. A corrupt/unreadable previous `facts.json` is treated as empty, never crashes the export.

**Repo list sourcing**
23. `_board_repos()` returns deduplicated repos from `board_registry.list_boards(include_archived=True)`.
24. An unreadable/corrupt board registry → `None`, not `[]`/crash.

**Recurrence probe (`lib/purpose_metrics.py`)**
25. `_facts_tests_gap()` returns `0.0` when the published snapshot or a fresh gather can't be read (matches this file's existing "dependency-failing-reads-zero" convention, e.g. `_banner_skill_count_drift`).
26. Returns the correct % gap for mocked published-vs-fresh totals; registered in `PROBES["facts-tests-gap"]` with limit `5.0`.

**Housekeeping (the constraint found above)**
27. `lib/tests/test_instance.py::test_the_grandfathered_list_only_shrinks` passes once `brain-map/scripts/facts.py` is removed from `lib/tests/instance_grandfathered.txt`.
28. `lib/tests/test_instance_move.py::test_the_brain_map_facts_read_run_results_from_the_instance` is deleted (nothing left to guard).

## Decisions

None. The repo-scope (board repos, including archived, since the count is historical), the site-test-counting method (actually running the two small `node --test` files rather than a static regex), and the facts.json shape (additive `tests_python`/`tests_js`/`tests_site` and `<figure>_counted_on` keys) are all reversible implementation defaults that follow directly from the ticket's own spec — none change product scope or need Gil's taste.

## Task List

1. `brain-map/scripts/facts.py`: replace `_merged_pipeline_prs()`'s title search with `_board_repos()` (via `board_registry.list_boards(include_archived=True)`) + `_closed_prs(repo)` (paginated REST `/pulls?state=closed`) + `_merged_pipeline_prs_total(repos)` (fails whole-to-`None` on any repo error or empty repo list); drop the now-unused `import instance` / `bench/metrics` glob.
2. `brain-map/scripts/facts.py`: add `_pytest_collected()`, `_vitest_listed(dashboard_dir)`, `_site_tests_collected(site_dir)`; change `compute_facts()`'s signature from `test_runs` to `tests_python`/`tests_js`/`tests_site`, writing each part when present and the `tests` total only when all three are present.
3. `brain-map/scripts/facts.py`: add the pure `merge_with_previous(fresh: dict, previous: dict) -> dict` (per-figure carry-forward + `<figure>_counted_on`); update `gather()` to call the new helpers.
4. `brain-map/scripts/facts.py`: rewrite the module docstring's field list to describe the new sources (no `"Implement G-Eskayo/..."` phrase).
5. `brain-map/export_snapshot.py`: `write_facts()` reads the out_dir's existing `facts.json` (if any, tolerating corrupt/missing) as `previous` and calls `merge_with_previous` before writing.
6. `lib/tests/instance_grandfathered.txt`: remove the `brain-map/scripts/facts.py` line.
7. `lib/tests/test_instance_move.py`: delete `test_the_brain_map_facts_read_run_results_from_the_instance`.
8. `lib/purpose_metrics.py`: add `_facts_tests_gap()` and register `PROBES["facts-tests-gap"]` (limit `5.0`).
9. Write all tests listed above (`brain-map/scripts/test_facts.py`, `brain-map/scripts/test_export_snapshot.py`, `lib/tests/test_purpose_metrics.py`, `lib/tests/test_instance.py`/`test_instance_move.py` updates) before the corresponding implementation.
10. Run the full Python suite (`pytest`, repo root) and the dashboard suite, confirm green.
11. Before opening the PR: hand-count merged `pipeline/*` PRs across the board repos and the current collected-test totals on `main`, and put both the hand count and the computed count in the PR description (acceptance criteria 1 and 2 require the PR to show both).
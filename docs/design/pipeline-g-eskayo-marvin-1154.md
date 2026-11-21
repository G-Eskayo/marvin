## North-star fit

- **Reuses before adding anything new:**
  - `lib/board_registry.py:list_boards()` for "every repo the board covers" — it already returns the live (non-archived) `{repo, name, ...}` list the dashboard's Activity tab uses, and `lib/` is already on `facts.py`'s `sys.path` (`brain-map/scripts/facts.py:27`), so no new path-finding code is needed.
  - The REST-pagination/`_gh_json` idiom already duplicated in `lib/purpose_metrics.py:953` and `lib/incident_ladder.py:451` (`subprocess.run(["gh","api",path])`, paginate on `page=`/`per_page=100` until an empty page) — this is the established in-repo pattern for staying off the GraphQL budget, matching exactly what the ticket asks for.
  - The `sys.executable -m pytest --collect-only -q -p no:cacheprovider` subprocess shape from `bench/tests/test_hidden_checks_not_collected.py:20` for counting Python tests without running them.
  - `site/scripts/facts.mjs` (already in the repo, `npm run facts` in `site/`) solves the *same two subproblems* — counting merged `pipeline/*` PRs by `head.ref`, and `pytest --collect-only` + `npx vitest list` totals — for the static site's own marketing facts. It's JS, hand-run, and rounds its numbers ("100+"), so it isn't reusable code, but its exact regexes/flags (`(\d+) tests? collected`, `vitest list` line-count, `headRefName.startsWith('pipeline/')`) are a working precedent I'm reusing directly rather than re-deriving.
  - `bin/gh` (the GitHub-gate wrapper) already intercepts every bare `gh` call via PATH — new REST calls use plain `["gh", "api", ...]`, same as existing code, so rate-limit cooldown/budget/spacing comes for free.
- **Simplest sufficient approach:** no new output file. The "last good value and date" fallback is read straight back out of the already-public, already-deployed `facts.json` (unformat a `"1,234"` string to `int`) rather than adding a sidecar or restructuring `counted_on` into a nested object. New fields (`tests_pytest`, `tests_vitest`, `tests_site`, and `<field>_counted_on` keys) are purely additive; the existing flat tile keys (`skills`, `tests`, `prs_merged`, `agents`, `decisions`, `machines`, `counted_on`) keep their current shape and meaning, satisfying "Unchanged: the live tiles."
- **Tokens:** zero model tokens — this is a subprocess-heavy maintenance script (gh/pytest/vitest/node), not an LLM task. Spend is a bounded number of extra `gh api` calls (paginated per board repo, through the existing rate gate) plus one `pytest --collect-only`, one `npx vitest list`, one `node --test` run — work the repo's own test gate already does regularly.
- **Phone-OS direction:** not applicable. This is truthful self-reporting infrastructure (north star 3: "no hand re-counting"), not an OS-shaping decision.
- **User capability:** more capable — Gil stops hand-recounting public numbers and stops hand-verifying them against page copy. Pure bookkeeping automation; the north star 3 "coach, don't take over" carve-out doesn't apply here.
- **Machine:** wherever the nightly/on-commit snapshot export already runs today (unchanged). The three new subprocess sources need the dashboard's `node_modules`, Node, and the MARVIN venv's pytest — exactly why they must degrade to "last good value," never 0, on a machine missing one of those.

## Files already read
`brain-map/scripts/facts.py`, `brain-map/scripts/test_facts.py`, `brain-map/export_snapshot.py` (`write_facts`, `export_snapshot`), `brain-map/scripts/test_export_snapshot.py` (`test_write_facts_*`), `lib/board_registry.py`, `lib/purpose_metrics.py` (`_gh_json`, pagination), `lib/incident_ladder.py` (pagination precedent), `lib/stamped.py` (rejected — its envelope adds `host`/`hardware_uuid`, which ADR 0050 forbids on this public file), `bench/tests/test_hidden_checks_not_collected.py`, `site/scripts/facts.mjs`, `site/package.json`, `dashboard/package.json`, `pytest.ini`, `conftest.py` (critically: `MARVIN_SELECTED_TESTS` scoping and the fake-`gh`-on-PATH test fixture), ADR 0050, ADR 0057, CONTEXT.md "Project boards" section, `docs/agents/decisions-format.md`.

## Key design points worth stating plainly

1. **`compute_facts()` no longer assembles `tests` itself.** It gets three independent fresh inputs (`pytest_collected`, `vitest_count`, `site_count`) and emits only the parts it has. A new pure function, `merge_with_previous(fresh, previous)`, does the carry-forward *and* derives `tests` as the sum of whichever parts end up present (fresh or carried). This keeps `compute_facts()` and `gather()`'s existing contracts intact and keeps the hard part (staleness) unit-testable without any file I/O.
2. **Carry-forward is per-source, not per-file.** Today, any failed source is merely *omitted*; AC3 requires it instead *keep its last value and date*. Four sources can fail independently (`prs_merged`, `tests_pytest`, `tests_vitest`, `tests_site`); each gets its own optional `<field>_counted_on`, present **only** when that figure was carried forward (absence means "as fresh as the file's top-level `counted_on`") — this is additive and avoids a redundant date on every normal run.
3. **The date must not creep forward across repeated failures.** A naive fallback to the file's own `counted_on` on every miss would silently advance a stale figure's apparent freshness every single day. `merge_with_previous` chains `previous["<field>_counted_on"] or previous["counted_on"]` — i.e. it only falls back to the *outer* date the first time a field goes stale, and pins to that original date on every subsequent miss. This is the single most important behavior to pin down with a test.
4. **`$MARVIN_SELECTED_TESTS` must be stripped before the subprocess `pytest --collect-only` call.** `conftest.py:64` narrows collection to only the files `lib/affected_tests.py` selected for the current change when that env var is set (marvin#826) — exactly the kind of "only a subset ran" trap that produced this ticket's original bug (#1153). If this var leaks into `_pytest_collected`'s subprocess environment, the "whole suite" count silently becomes a partial one again. The subprocess env must explicitly drop it.
5. **`npx vitest list` must not silently reach the network.** Use `npx --no-install vitest list` so a machine with no `dashboard/node_modules` fails fast and visibly instead of `npx` fetching a possibly-wrong vitest from the registry.
6. **Node's test runner has no "list, don't run" mode** for `site`'s `node --test`. Running them and parsing the TAP summary's `# tests N` line (not gated on exit code, since a failing test must still be counted, not vanish) is the correct "size of the site's tests" signal.

## Tests to write first

Mapped to the ticket's "How we'll try to break it" (and its implied Attacks), plus gaps I found while reading the actual sources:

**PR counting (`_merged_pipeline_prs`, `_gh_json`)**
1. A closed-and-merged PR with `head.ref` starting `pipeline/` → counted, regardless of its title (fixes the original title-search defect).
2. A PR titled `"Implement G-Eskayo/x#5"` whose `head.ref` does **not** start `pipeline/` → not counted (proves the defect is actually fixed, not just renamed).
3. A closed-but-not-merged PR (`merged_at: null`) on a `pipeline/*` branch → not counted.
4. A pipeline PR whose title was hand-edited after merge → still counted (title is irrelevant to the new logic).
5. A repo with >100 closed PRs: pagination (`page=1,2,...`) sums every page, stopping only on an empty page.
6. `fetch` raises (GitHub refuses / rate-limited, including the gate's exit-75 deferral) on *any one* board repo → the whole `prs_merged` computation returns `None` (never a silent undercount presented as truth).
7. The board registry is empty (`list_boards()` → `[]`, e.g. first run ever or a wiped registry) → `None`, never `0` (0 boards is "unknown," not "zero PRs").
8. A malformed REST response (non-list JSON, or a list containing non-dict items) → treated as failure (`None`), not a crash.

**Test counting (`_pytest_collected`, `_vitest_count`, `_site_test_count`)**
9. `pytest --collect-only` output `"4454 tests collected, 8 errors in 12.34s"` → returns `4454` (the rest are counted) and a warning naming the 8 errors is surfaced (stderr), never inflated and never silently dropped.
10. `pytest --collect-only` reporting `0 tests collected` / "no tests ran" (returncode 5) for a whole-repo run → treated as a failure (`None`), since a genuine 0 across the whole suite is never real.
11. The subprocess for (9)/(10) explicitly has `MARVIN_SELECTED_TESTS` stripped from its environment even when the calling process has it set — asserted by passing an injected `run` that inspects the `env` it was called with.
12. `run()` raises (pytest missing, or times out) → `None`.
13. `npx --no-install vitest list` failing (no `dashboard/node_modules`) → `None`, "left out with a reason," not `0`.
14. `site/scripts/*.test.mjs` present, `node --test --test-reporter=tap` returns a `# tests N` summary with some failures → still returns `N` (count ran, not just passed).
15. No `.test.mjs` files found under `site/scripts` → `None`, not `0`.
16. `tests == tests_pytest + tests_vitest + tests_site` exactly when all three are fresh (AC2, direct).

**Carry-forward / staleness (`merge_with_previous`) — AC3**
17. One source fails this run, `previous` has its last value + no previous `<field>_counted_on` yet → carried value is `int`-parsed correctly from a comma-formatted previous string, and its date falls back to `previous["counted_on"]`.
18. The same source fails **again** next run → the date stays pinned to the *original* success date, not the (also-missing) previous run's generation date (the no-creep regression test described above — run it for ≥3 consecutive failures).
19. A source that never had a previous value at all (new, never-succeeded) and fails now → omitted entirely, never `0`, no bogus date.
20. A previous `facts.json` predates this feature (only has the old flat `tests` + `counted_on`, no part-level keys) and **all three** test sources fail on the first post-upgrade run → the old flat `tests` is still carried forward directly rather than vanishing (migration bootstrap).
21. `previous["tests_pytest"]` is corrupted by hand (e.g. `"N/A"`) → carry-forward for that field fails closed (omitted), not a crash.
22. `write_facts()`'s existing two tests (`test_write_facts_puts_formatted_facts_next_to_the_map`, `test_write_facts_failure_writes_nothing_and_does_not_block_the_map`) still pass unmodified — proves the new "read existing facts.json" step is a no-op when nothing is missing, and a hard exception from `gather()` still blocks the whole write (unchanged contract).
23. `write_facts()` with a genuinely corrupt existing `facts.json` on disk (bad JSON) → treated as "no previous data" (empty dict), never a crash.
24. Calling `gather()`/`compute_facts()` twice in a row with identical inputs → identical output (idempotency/determinism stand-in for "repeats and concurrency," since the real concurrency risk — two writers racing on the same file — is `write_facts`'s pre-existing non-atomic write, out of this ticket's named scope; noted below, not silently expanded into).
25. `skills`/`agents`/`decisions`/`machines` keep today's existing "omit, don't carry-forward" behavior unchanged (the ticket's misuse list never asks these four to grow a fallback; the regression test proves I didn't generalize carry-forward to them by accident).

## Decisions

<!-- marvin:decisions -->
### schema: facts.json gains new keys for the per-source breakdown and staleness dates — is the additive shape below acceptable?
- [ ] A: Yes — add `tests_pytest`, `tests_vitest`, `tests_site` (the parts) plus `prs_merged_counted_on`, `tests_pytest_counted_on`, `tests_vitest_counted_on`, `tests_site_counted_on` (present only when that figure was carried forward from a previous run). Existing keys (`skills`, `tests`, `prs_merged`, `agents`, `decisions`, `machines`, `counted_on`) are untouched.
- [ ] B: Add the three part-values but skip the per-part `_counted_on` keys — staleness is only ever visible in MARVIN's own logs/stderr, not in the public file.
- [ ] C: Something else (note below).

## Task List

1. `brain-map/scripts/facts.py`: replace `_merged_pipeline_prs()` with a `_gh_json(path)` helper (mirrors `lib/purpose_metrics.py:_gh_json`) and a paginated `_merged_pipeline_prs(repos, fetch=None)` that sums merged, `pipeline/*`-head PRs per repo via `repos/{o}/{r}/pulls?state=closed&per_page=100&page=N`, returning `None` on any repo failure or an empty repo list.
2. Add `_pytest_collected(repo_root, run=None)`: runs `sys.executable -m pytest --collect-only -q -p no:cacheprovider` with `MARVIN_SELECTED_TESTS` stripped from its env; parses `"N tests? collected"` and an optional `", M errors?"`, warns on stderr for errors, returns `None` on 0/failure/timeout.
3. Add `_vitest_count(repo_root, run=None)`: runs `npx --no-install vitest list` in `dashboard/`; counts non-empty stdout lines; `None` on failure.
4. Add `_site_test_count(repo_root, run=None)`: globs `site/scripts/*.test.mjs`; runs `node --test --test-reporter=tap <files>` in `site/`; parses `"# tests N"`; `None` if no files or no match.
5. Update `compute_facts()`: drop `test_runs`; add `pytest_collected`, `vitest_count`, `site_count` params; emit only `tests_pytest`/`tests_vitest`/`tests_site` (never assembles `tests` itself anymore).
6. Add `merge_with_previous(fresh, previous)`: per-field carry-forward for `prs_merged`/`tests_pytest`/`tests_vitest`/`tests_site` with chained `<field>_counted_on`; derives `tests` from whichever parts are present after merging, with the legacy-flat-`tests` bootstrap fallback.
7. Update `gather()`: get `repos` from `import board_registry; [b["repo"] for b in board_registry.list_boards()]`; call the four new source functions; drop the `bench/metrics/ticket-*.json` reading entirely; pass the new inputs into `compute_facts()`.
8. Update `brain-map/export_snapshot.py:write_facts()`: read the existing `out_dir/facts.json` (tolerate missing/corrupt → `{}`), call `facts_mod.merge_with_previous(fresh, existing)` before `facts_mod.formatted(...)`.
9. Update `facts.py`'s module docstring to describe the new `tests`/`prs_merged` sourcing and the new per-part/`_counted_on` fields.
10. Rewrite `brain-map/scripts/test_facts.py`: replace the `test_runs=`-based tests with the pytest/vitest/site-based ones, and add all 25 tests above (merged into the existing file's style/fixtures where they overlap, e.g. the existing "source left out, not zero" and "skills"/"decisions" tests stay, just dropping `test_runs=` from their call sites).
11. Add the two or three new/adjusted assertions to `brain-map/scripts/test_export_snapshot.py` for `write_facts()`'s merge-with-previous step (tests 22–23 above), leaving the two existing tests passing unmodified.
12. Run the full Python suite (not a scoped subset) plus `dashboard`'s `npm test` to confirm nothing else imports the removed `test_runs` parameter or the old `_merged_pipeline_prs()` signature.
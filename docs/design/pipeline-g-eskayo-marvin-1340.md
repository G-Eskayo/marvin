## North-star fit

**Reuses:** the `outside_state` marker + `_has_playwright()`/`_live()` skipif pattern already proven in `lib/tests/test_portfolio_parity.py:33-58` for any assertion that needs the real browser or dev site (never mocked — matches north-star "test against the real collaborator's rules"). The injectable-`runner` pattern already used by `portfolio_apply.wp_base()`/`regenerate_pages()`/`portfolio_add_project.create_page()` (`lib/portfolio_apply.py:44,151-180`; `lib/portfolio_add_project.py:80-101`) for the new wp-cli-container check. The existing marvin#585 guard (`lib/portfolio_inventory.py:177-187`, pinned by `lib/tests/test_portfolio_inventory.py:117-126`) for the "refuse before writing" shape — this ticket extends that same shape to a second failure mode (silently-short crawl) instead of inventing a new one. `portfolio_migrate.py`'s "content-loss guard" principle (never silently lose good data) is echoed, not literally shared code, in the new placement-drop guard.

**Simplest sufficient approach:** the root cause (relying on a `?page_id=` redirect) is removed outright — `wp post list --fields=...,url` already gives WordPress's own permalink per page, so the crawl stops depending on redirect behaviour at all, rather than adding retry/detection logic around the fragile redirect. The "fewer pages than WordPress lists" guard and the "previous inventory kept" rotation are each one small pure function (`missing_pages`, `rotate_inventory`), kept out of the browser-touching code per the file's own documented split ("Pure parts... are unit-tested; `collect` is the thin browser layer").

**Tokens/cost:** `ensure_wpcli_running()` adds one `docker inspect` (~tens of ms) per wp-cli call during a crawl (≈ page count + 1); on a 40-page site that's ~2s of overhead against a crawl that already takes much longer per page (full-page screenshot, `networkidle`). Spent deliberately: self-healing (no re-run, no manual `docker start`) is worth a few seconds. Not cached across calls — a fresh CLI process per crawl makes that unnecessary complexity.

**Phone-OS / capability:** this is a reliability fix for data MARVIN's own dashboard shows Gil (parity tests, Site inventory, element library) — it stops MARVIN from quietly lying about the site, which is a precondition for Gil trusting any of the portfolio tooling to act autonomously later. Leaves Gil more capable (he no longer has to notice a short crawl by hand, as happened 2026-11-16) without taking any judgment away from him — overwrites still require `--accept-drop`, a deliberate human act.

**Where it runs:** pure Python, no machine preference; the two outside_state tests need the dev site (localhost:8080) and Playwright, so they only run meaningfully on a Mac with the dev site up (same as the existing parity tests).

**Scope call (not a Decision — reversible, low-risk, I'm confident):** the wp-cli container self-heal (`ensure_wpcli_running`) is applied at all three places that currently emit the fragile "(is the dev site running?)" message (`portfolio_inventory.py`, `portfolio_apply.py::regenerate_pages`, `portfolio_add_project.py::create_page`), not just the one in the bug report, since leaving two of three unfixed would be an inconsistent half-fix of the identical symptom. This requires a one-line addition to the fake `runner`/`_runner` fixtures in `test_portfolio_apply.py` and `test_portfolio_add_project.py` (to answer `docker inspect` with "true") so existing happy-path tests keep passing — included in the task list below.

No north star argues against this work.

## Tests to write first

The ticket has no "How we'll try to break it"/Attacks section, so these are derived from the acceptance criteria plus the standard misuse checklist (bad/empty/malformed input, each dependency failing, repeats, stale state, a person's mistakes):

**`lib/tests/test_portfolio_inventory.py`**
1. `page_path()` derives a page's path from WordPress's own `url` field, not a redirect — the literal regression case (a `?page_id=` that would return `/` with no redirect still yields the real path).
2. `page_path()` falls back to `/` when `url` is missing/empty (malformed wp-cli row) — so it's caught by the completeness guard rather than silently miscounted.
3. `missing_pages()` is `[]` when every WP id was captured.
4. `missing_pages()` names every WP page whose id was not captured (title, falling back to slug, falling back to id).
5. `missing_pages()` on an empty WP list → `[]` (empty input).
6. `missing_pages()` with duplicate ids in the WP list doesn't crash or double-report (malformed input).
7. (existing, keep green, unchanged) `collect()` refuses and keeps the old inventory when wp-cli lists no pages at all.
8. NEW: `collect()` refuses the same way when wp-cli returns valid JSON that is not a list (e.g. `"{}"`) — currently this falls through to `for p in wp_pages` iterating dict keys and crashes with `TypeError`; add an `isinstance(wp_pages, list)` guard plus this test (malformed-input case the current code doesn't actually handle).
9. `rotate_inventory()` is a no-op the first time (no `inventory.json` yet).
10. `rotate_inventory()` moves the current file to `inventory.prev.json`, and a second call overwrites `inventory.prev.json` with the newer one (repeat-run case, exactly one previous kept).
11. **outside_state** (`_has_playwright()`/`_live()` skipif, mirroring `test_portfolio_parity.py`): a real `collect()` run against the dev site captures exactly as many pages as `wp post list` lists, each under a distinct path — the end-to-end proof that the collapse-to-`/` bug is gone.

**`lib/tests/test_portfolio_elements.py`**
12. `_finish()` refuses to write when new placements are 0 against an on-disk file with placements > 0; file on disk is unchanged.
13. refuses when new placements drop by more than half (20 → 9).
14. does **not** refuse at exactly half (20 → 10) — boundary, "more than half" only.
15. does not refuse when no file exists yet (first capture, including a legitimately-zero-placement element — the real `button-download` case already noted in CONTEXT.md).
16. does not refuse when the on-disk baseline was already 0 placements.
17. `accept_drop=True` writes anyway despite a qualifying drop.
18. a refused result still reports the placements actually found (for the CLI to show) without touching the on-disk file.
19. a corrupted/unreadable existing JSON file on disk is treated as "no baseline" (writes proceed) rather than crashing — a person's-mistake case (half-written file from a killed previous run).
20. `main()`'s `--accept-drop` flag works mixed with positional element ids, and is absent by default.

**`lib/tests/test_portfolio_apply.py`**
21. `ensure_wpcli_running()` does nothing (no `docker start`) when the container already reports running.
22. starts a stopped container and succeeds when the post-start check reports running.
23. raises a plain "...is stopped and could not be restarted" error when a restart doesn't bring it up — never the vague "(is the dev site running?)" text.
24. raises a plain "...was not found" error when `docker inspect` itself fails (no such container) — distinct message from "stopped".
25. update the shared `_runner` fixture to answer `docker inspect` with "true" by default, and confirm the existing `regenerate_pages`/`apply` tests still pass unchanged (regression guard for the fixture change itself).

**`lib/tests/test_portfolio_add_project.py`**
26. update `runner()` the same way; confirm `create_page`/`add_project` tests still pass.
27. (reuse 23/24's behaviour through `create_page` once wired — no new assertion needed beyond confirming the RuntimeError/AddProjectError still surfaces.)

Not tested (acknowledged gaps, consistent with existing baseline — no file locking exists anywhere else in this module set either): concurrent `collect()`/`capture_many()` runs racing on the same files; filesystem permission errors on write.

## Task List

1. `lib/portfolio_apply.py`: add `_wpcli_running(runner=_run) -> bool | None` and `ensure_wpcli_running(runner=_run) -> None` (restarts a stopped container, raises a specific message if it's stopped-and-can't-restart or not found at all).
2. `lib/tests/test_portfolio_apply.py`: extend the shared `_runner` fixture to answer `docker inspect` with `"true"`; add tests 21-25 above.
3. `lib/portfolio_apply.py::regenerate_pages`: call `ensure_wpcli_running(runner)` before the first `wp post list`.
4. `lib/portfolio_add_project.py::create_page`: call `pa.ensure_wpcli_running(runner)` before the first `wp post list`.
5. `lib/tests/test_portfolio_add_project.py`: extend its `runner()` fixture the same way; confirm existing tests pass (task 26-27).
6. `lib/portfolio_inventory.py::_wpcli`: call `pa.ensure_wpcli_running()` before the subprocess call.
7. `lib/portfolio_inventory.py`: add `page_path(wp_page) -> str` (pure); change the `--fields=` list to include `url`; replace the `?page_id=` + `urlparse(page.url).path` redirect dance with `page.goto(base + page_path(wp))` using the path from wp-cli directly.
8. `lib/portfolio_inventory.py`: add `isinstance(wp_pages, list)` to the existing empty-listing guard (fixes the dict-iteration crash on malformed wp-cli JSON).
9. `lib/portfolio_inventory.py`: track `captured_ids` in the crawl loop; add `missing_pages(wp_pages, captured_ids) -> list[dict]` (pure); after the crawl, raise naming any missing pages and skip the write, before producing `result`.
10. `lib/portfolio_inventory.py`: add `rotate_inventory(out_dir)` (pure) and call it immediately before writing the new `inventory.json`.
11. `lib/tests/test_portfolio_inventory.py`: add tests 1-10 above (pure) and test 11 (outside_state).
12. `lib/portfolio_elements.py::_finish`: add `accept_drop: bool = False` param; before writing, compare new placements against the on-disk file's `usage.placements` (if any) and set `result["write_refused"]` instead of writing when dropped to 0 or by more than half and `accept_drop` is false.
13. `lib/portfolio_elements.py::capture_many` / `capture`: thread `accept_drop` through to `_finish`.
14. `lib/portfolio_elements.py::main`: switch to `argparse` with positional element ids and `--accept-drop`; print a clear "REFUSED to write" line for any refused element.
15. `lib/tests/test_portfolio_elements.py`: add tests 12-20 above.
16. Run the full `pytest` suite for `lib/` (not just the touched files) before calling this done, per the full-suite-before-hand-merge convention.
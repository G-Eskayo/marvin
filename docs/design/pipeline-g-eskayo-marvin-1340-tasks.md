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
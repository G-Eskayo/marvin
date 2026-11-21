## North-star fit

- **Reuses before adding anything new:** the module's own established split between *pure, tested* helpers and a *thin, untested browser layer* (`lib/portfolio_inventory.py` docstring + `button_signature`/`variant_id`/`group_buttons`/`classify_page`, all pure and unit-tested while `collect` itself is not) — I extend that split rather than writing a Playwright-mocking integration harness. The existing `--fields=...` guard against an empty WordPress listing (`portfolio_inventory.collect`, marvin#585, `test_collect_refuses_to_crawl_when_wordpress_cannot_list_its_pages`) is the direct template for the new "refuse to write" guards. `lib/portfolio_apply.py`'s `_run`/`runner=` dependency-injection pattern (used by `regenerate_pages`, tested via the `_runner()` fake in `test_portfolio_apply.py`) and its existing `DOCKER`/`WPCLI` constants are reused for the new container-restart helper instead of inventing a second way to shell out to Docker. `lib/portfolio_sync_dev.py:judge_evaluation` (errors fail a step, warnings don't; already tested) is the template for a new `judge_capture`, so a refused element-capture actually fails the pipeline step instead of being silently reported as success — the exact failure mode in the bug ("`portfolio_elements.py` ran right after the failed crawl").
- **Simplest sufficient approach:** stop depending on WordPress's redirect at all — ask wp-cli for each page's own `url` once (one extra field on an API call already being made), and navigate straight there. That removes the whole class of bug instead of patching around the redirect. The two "refuse to overwrite" guards (pages, elements) are each one small comparison against data already on disk or already fetched — no new state, no new service.
- **Where it spends/saves tokens:** this is a plan for Python-only, deterministic, Playwright/wp-cli-backed tooling — no LLM calls added or removed. It saves *future* tokens/incidents: a short crawl can no longer quietly become the reference data, so nobody has to notice-and-hand-restore files again (as happened here).
- **Phone-OS direction:** neutral — backend data-integrity fix for one project's tooling, not user-facing or OS-shaped.
- **More capable or more passive:** more capable — Gil stops needing to notice "this looks wrong" by eyeballing page counts after the fact; the tool now tells him immediately and keeps the last-known-good copy.

## Decisions

<!-- marvin:decisions -->
### page-drop-threshold: How strict should the "missing pages" refusal be? (optional)
- [ ] A: Zero tolerance — refuse if even one WordPress-listed page wasn't captured (implemented as the default in this PR)
- [ ] B: Tolerate a small gap — only refuse past some percentage missing (e.g. >10%), to survive one flaky page load without blocking the whole crawl

## Tests first

All new tests are pure/unit-level (tmp_path + fakes), no live docker/wp-cli/Playwright — matching how this file's existing wp-cli/browser-dependent code is already tested (the one precedent, `test_collect_refuses_to_crawl_when_wordpress_cannot_list_its_pages`, also never touches Playwright).

**`lib/tests/test_portfolio_inventory.py`**
1. `resolve_page_targets` uses each WordPress page's own `url`, never collapsing distinct pages to `/` (the exact marvin#1340 symptom) — feed pages whose paths are *not* `/`, assert each keeps its own path.
2. `resolve_page_targets` appends the `/` home fallback once, and skips it when a WordPress page already resolves to `/` (configured front page) — no duplicate target.
3. `collect` refuses outright (no Playwright launch) when any WordPress page is missing a `url` field — malformed/older wp-cli output; old `inventory.json` untouched (misuse: dependency returns unexpected shape).
4. `missing_pages` names every WordPress-listed page (and `/`) not present in the captured set, with its title.
5. `missing_pages` is empty when every listed page (and `/`) was captured.
6. `finalize` raises and leaves the old `inventory.json` and any old `inventory.prev.json` untouched when pages are missing — names the missing page(s) in the message.
7. `finalize` copies the existing `inventory.json` to `inventory.prev.json` before writing the new one, when nothing is missing.
8. `finalize` writes cleanly with no previous `inventory.json` to back up (first-ever run; empty/fresh directory).
9. `finalize` repeatedly called (simulating a re-run) always backs up only the *immediately preceding* copy, never accumulates (`inventory.prev.json` gets overwritten, not appended).
10. `collect` recovers when wp-cli's page listing fails because the wp-cli container is stopped: `restart_wpcli_container` is consulted, the listing is retried once, and the crawl proceeds normally (monkeypatching `inv._wpcli` to fail once then succeed, and `portfolio_apply.restart_wpcli_container` to report "restarted").
11. `collect` raises naming the container as stopped (not "is the dev site running?") when the restart itself fails; old inventory kept.

**`lib/tests/test_portfolio_elements.py`**
12. `_finish` refuses to write when the new placement count is `0` against a non-zero count already on disk; the old file on disk is untouched; `result["written"] is False` and `result["refused"]` names old → new counts.
13. `_finish` refuses to write when the new count is less than half the count on disk (boundary: exactly half is **allowed**, one-under-half is refused).
14. `_finish` writes through a would-be-refused drop when `accept_drop=True`, overwriting the file.
15. `_finish` writes normally (no guard) when there is no existing file yet (first-ever capture, even with `0` placements).
16. `_finish` writes normally when the new count is unchanged or higher than on disk.
17. `_finish` doesn't crash and treats "no prior count to compare" as the no-guard case when the existing on-disk file is corrupt JSON (bad/malformed input).
18. `parse_cli_args`: no args → every element id, `accept_drop=False`; one id + `--accept-drop` → that id only, `accept_drop=True`; `--accept-drop` alone → every id, `accept_drop=True`.

**`lib/tests/test_portfolio_apply.py`**
19. `restart_wpcli_container` starts a stopped container and reports it, signalling "retry worth it".
20. `restart_wpcli_container` reports the container is already running (so the fault lies elsewhere) and signals "don't retry".
21. `restart_wpcli_container` names the container as not found when docker can't inspect it (container deleted/renamed).
22. `restart_wpcli_container` names the container as stopped-and-unrestartable when `docker start` itself fails (e.g. permission denied), without leaking any secret into the message.
23. `regenerate_pages` recovers transparently (no exception) when the initial page listing fails because the container was stopped but the restart+retry succeeds.
24. `regenerate_pages` raises naming the container as stopped (not "is the dev site running?") when the restart fails.

**`lib/tests/test_portfolio_add_project.py`**
25. `create_page` recovers transparently when the initial listing fails but the container restarts and the retry succeeds.
26. `create_page` raises naming the container as stopped when restart fails, leaving the manifest untouched (reuses the existing "failed page creation leaves the manifest alone" assertion style).

**`lib/tests/test_portfolio_sync_dev.py`**
27. `judge_capture`: a refused element write (`written: False`) fails the capture step and reports which element and why — mirrors the existing `judge_evaluation` tests exactly.
28. `judge_capture`: every element written → step is OK, with the same summary message shape as today.

## Task List

1. `lib/portfolio_apply.py`: add `restart_wpcli_container(runner=_run) -> tuple[bool, str]` using the existing `DOCKER`/`WPCLI` constants (`docker inspect` → `docker start` → report). Returns whether a retry is worth it and a human-readable reason.
2. `lib/portfolio_apply.py`: wire `regenerate_pages` to call `restart_wpcli_container()` and retry its page listing once when the initial listing fails, replacing the blind "is the dev site running?" message with the specific reason when it still can't proceed.
3. `lib/portfolio_add_project.py`: same wiring in `create_page` (reuse `pa.restart_wpcli_container`).
4. `lib/portfolio_inventory.py`: same wiring in `collect`'s initial `_wpcli(["post", "list", ...])` call.
5. `lib/portfolio_inventory.py`: add `url` to the wp-cli `post list --fields=...`; validate every listed page has a non-empty `url` (refuse early otherwise).
6. `lib/portfolio_inventory.py`: add pure `resolve_page_targets(wp_pages)`; replace the `?page_id=` navigation + `urlparse(page.url).path` redirect-dependent logic in `collect`'s crawl loop with it (navigate straight to each page's own path).
7. `lib/portfolio_inventory.py`: add pure `missing_pages(wp_pages, captured_urls)` and `finalize(result, wp_pages, out_dir)` (missing-pages refusal, then `inventory.json` → `inventory.prev.json` backup, then write); replace `collect`'s final inline write with a call to `finalize`.
8. `lib/portfolio_inventory.py`: remove the now-unused duplicate `WPCLI_CONTAINER` constant (dead since `_wpcli` already goes through `portfolio_apply.wp_base()`).
9. `lib/portfolio_elements.py`: thread `accept_drop: bool = False` through `capture`, `capture_many`, `_finish`; in `_finish`, read the existing on-disk file's `usage.placements` before writing, refuse (set `written=False`, `refused="..."`, skip the write) when the new count is `0` or less than half the old count, unless `accept_drop`.
10. `lib/portfolio_elements.py`: add `parse_cli_args(argv)` and update `main()` to support `--accept-drop`, and to print a distinct line for any refused element.
11. `lib/portfolio_sync_dev.py`: add `judge_capture(results, layouts)` (mirrors `judge_evaluation`); update the `capture()` step closure in `run()` to use it, so a refused element capture fails that pipeline step instead of reporting success.
12. Write all tests listed above alongside each change (red → green per file).
13. Run the full `lib/tests` suite (not just the touched files) before considering this done, per the "full suites before a hand-merge" rule.
## North-star fit

**Reuses:** `lib/ticket_pipeline.py:204-226` (`_background_checks`/`_owner_decisions`/`_parked`) — the existing "best-effort side step that never breaks the scan" pattern — for wiring the low-disk-guard's park sweep, instead of inventing a new error-handling convention. `lib/cold_store.py:154-173` (`local_manifest`) and `279-283` (`remote_manifest`) are extended (not duplicated) to take an optional `part` so re-park can hash just the changed subset. `lib/cold_store.py:138-151` (`compare`) is reused as-is for verifying uploaded subsets. `_swap`/`_finish_swap`'s invariant — never delete local bytes until the authoritative remote/catalog state is durably written — is carried into the new drop step, though re-park doesn't need the literal two-rename (there's no folder↔marker substitution left to do once a marker already exists; only files are being removed from inside it). No new file is added; everything lands in `lib/cold_store.py`, `lib/ticket_pipeline.py`, and their test files.

**Simplicity:** the ticket's own bug is narrow — `park()`'s existing-marker branch (`cold_store.py:372-375`) short-circuits before doing any work. The fix is to replace that short-circuit with a real re-park path, reusing first-park's hash/verify/write machinery at file-granularity instead of whole-folder granularity (because, unlike a first park, only part of the tree is present).

**Resource cost:** re-park only ever hashes/reads bytes that are *physically local* (`local_manifest(path)`, already O(bytes present)) and only re-hashes the *changed* subset remotely (scoped `remote_manifest(name, part=rel)`), never the whole cold copy — this matters because a multi-GB parked entry with one small changed result file must not trigger a full-entry remote rehash. The low-disk sweep only runs when disk is already below the configured floor, not on every scan, so it spends nothing when there's nothing to fix.

**Phone-OS fit:** disk hygiene that heals itself from a trigger (job end, guard check) rather than a cron poll is exactly the "nothing polls, a caller asks" shape the rest of cold_store already uses — and it's what keeps a Mac usable unattended, which is a precondition for MARVIN running on any always-on device.

**More capable, not more passive:** this removes a manual workaround (Gil hand-parking sub-folders to scrape together 0.4 GB margin) with no new human steps — purely infrastructure.

## Tests to write first (all in `lib/tests/test_cold_store.py` unless noted)

From the ticket's "How we'll try to break it":
1. `test_repark_after_a_local_file_changed_keeps_the_new_version` — park, `ensure --part`, mutate that file's bytes, `park` again, `.marker()`'s sha updates, and a fresh `ensure` on another machine fetches the *new* bytes, not the old ones.
2. `test_an_interrupted_repark_leaves_nothing_lost_and_the_next_call_finishes_it` — park, `ensure --part`, kill the upload rsync mid-way (reuse the `_rsync_wrapper` "once" pattern already in the file), assert nothing local is missing/corrupted, then a second `park` (or `ensure`) completes it and the remote copy ends up correct.
3. `test_a_folder_in_use_during_repark_is_refused_nothing_moved` — park, `ensure --part`, set `in_use` to return a fake process, `park` raises `BUSY`, local files untouched, remote entry unchanged.
4. `test_repark_stops_if_the_remote_manifest_sha_no_longer_matches_the_marker` — park, `ensure --part`, tamper the remote `manifest.json` like `test_a_tampered_manifest_on_the_cold_host_is_not_trusted_when_the_catalog_is_gone`, assert `park` raises `VERIFY_FAILED` and the local part is **not** deleted.

Misuse the ticket's section didn't name:
5. `test_repark_with_nothing_fetched_back_is_a_true_no_op` — park an already-fully-parked folder again (nothing local but the marker): zero rsync calls, zero ssh calls beyond `_finish_swap`'s none, same entry returned (covers "empty input" and preserves the existing idempotency test's guarantee).
6. `test_repark_drops_an_unchanged_fetched_part_with_no_network_upload` — park, `ensure --part X` (unchanged), `park` again: the part is deleted locally and **no rsync upload call** happens (sha-matched, no copy), only a scoped remote hash check.
7. `test_repark_uploads_a_brand_new_file_written_next_to_the_marker` — park, write a new file directly under the parked path (not via `ensure`), `park` again: it's uploaded, added to the manifest, then dropped; a later full `ensure` brings it back.
8. `test_two_concurrent_reparks_on_the_same_folder_serialize_and_only_one_moves_bytes` — mirror `test_two_ensure_calls_at_once_fetch_only_once`'s threading pattern for `park`.
9. `test_repark_when_the_cold_host_is_unreachable_fails_calmly_nothing_removed` — mirror `test_the_cold_host_being_off_fails_calmly_and_changes_nothing`, but starting from a marker with a fetched part present.
10. `test_repark_rebuilds_trust_when_the_local_catalog_is_gone` — mirror `test_a_marker_without_its_catalog_still_fetches_and_rebuilds_the_catalog` for the park direction.
11. `test_list_shows_local_bytes_for_a_half_fetched_entry_and_zero_once_reparked` — `list`'s dict and printed text both surface `local_bytes`.
12. `test_sweep_local_bytes_reparks_every_entry_with_bytes_present_and_skips_the_rest` — new `Store.sweep_local_bytes()` method, one entry with local bytes gets parked, one fully-parked entry is left alone, a park failure on one entry doesn't stop the sweep from trying the next.
13. `test_ensure_then_park_reparks_on_exit_and_never_masks_the_bodys_own_exception` (context manager) — normal exit re-parks; body raises `ValueError`, it still propagates even though `park()` inside `finally` fails with `BUSY`.
14. `test_cli_ensure_then_park_flag_reparks_after_fetching` — `main(["ensure", ..., "--then-park"])` drops the fetched part back down to just the marker.

`lib/tests/test_ticket_pipeline.py` (or wherever its guard tests live — confirm exact file before writing):
15. `test_background_checks_sweeps_cold_store_only_when_disk_is_already_low` — disk above floor → cold_store sweep not invoked (no stray hashing cost); disk below floor → sweep invoked and its exception is swallowed exactly like `_owner_decisions`/`_parked`.

## Decisions

None needed — no product-direction fork here. The few implementation calls (an integer `version` field on the entry bumped per re-park; re-park logging-not-raising park failures inside the trigger context manager; keeping `dispatch_concurrency.can_start_another` pure and putting the real disk/park sweep in `ticket_pipeline.py` instead) are dictated by the existing architecture split (pure guard logic vs. impure callers) and are stated above rather than left silent.

## Task List

1. `lib/cold_store.py`: extend `remote_manifest(name, part=None)` to scope-and-remap like `local_manifest` already does, keeping the no-`part` call sites (existing tests, `_trusted_manifest`) unchanged.
2. `lib/cold_store.py`: add a small diff helper (local manifest vs. trusted manifest → matched keys / changed-or-new keys), used only by re-park.
3. `lib/cold_store.py`: replace the `park()` existing-marker short-circuit (`:372-375`) with the real re-park path: lock → `_finish_swap` cleanup → `local_manifest(path)` of what's physically present → if empty, return the entry unchanged (no-op) → else busy check → `_trusted_manifest` (fails closed on sha mismatch) → diff → upload only changed/new paths via scoped `_rsync` (resumable) → scoped `remote_manifest(part=rel)` verify per changed path → write updated `manifest.json`/`entry.json` (bump `version`) via `_remote_write` → update local catalog → delete all locally-present data → rewrite the marker with `parts: []` and the new entry.
4. `lib/cold_store.py`: add `Store.local_bytes_present(path) -> int` (stat-only, no hashing) and surface `local_bytes` in `listing()` / `_print_listing()`.
5. `lib/cold_store.py`: add `Store.sweep_local_bytes()` — iterate `catalog_all()`, re-park every entry owned by this machine with `local_bytes_present > 0`, catching per-entry `ColdError` so one bad entry doesn't stop the rest.
6. `lib/cold_store.py`: add `Store.folder_for(target)` (thin wrapper over `_resolve`) and the `ensure_then_park` context manager built on it.
7. `lib/cold_store.py`: add `--then-park` to the `ensure` CLI subparser, calling `park(store.folder_for(target))` after a successful fetch.
8. `lib/ticket_pipeline.py`: add `_cold_store_sweep()` next to `_owner_decisions`/`_parked` (same never-breaks-the-scan contract), gated on `_free_disk_gb()` already being under `dispatch_concurrency.load()["guards"]["min_disk_gb"]`; call it from `_background_checks()`.
9. Run the full `lib/tests/test_cold_store.py` and `lib/tests/test_ticket_pipeline.py` (or equivalent) suites plus the project's full Python suite before considering this done, per the main-green/full-suite rule.
10. Update `CONTEXT.md`'s Cold store section (`:2050-2062`) with the **re-park** and **local bytes** terms so the lexicon stays accurate.
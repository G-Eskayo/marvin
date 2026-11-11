## North-star fit

**Reuses:** `lib/cold_store.py`'s own `_swap()`/`_finish_swap()`/`_write_marker()` (the existing two-rename, resumable swap primitive — `_repark` hands it a fresh marker reflecting the merged manifest instead of inventing a second deletion path), `_trusted_manifest()` (the sha-trust check — re-park gets "stop, never drop local data" for free), `local_manifest()`/`stat_snapshot()`/`compare()`/`remote_manifest()` (same byte-for-byte verify first `park()` already pays for, O(B) every call by existing design, so re-verifying the whole remote copy after a re-park costs nothing new in kind). For the CLI trigger, I'm reusing the `argparse.REMAINDER` "wrap a command, clean up after" shape already used five times in this codebase (`test_slot.py:222 run`, `model_cache.py:178 link`, `memory_guard.py:481`, `vm_run.py:279`, `box_trial.py:165`) rather than inventing a Python context manager — there is currently no Python caller of `cold_store` to attach a context manager to; every caller is a shell job via the CLI, so `--then-park` fits the dominant pattern. For the low-disk guard, I'm reusing `disk_triggers.preflight()`'s existing injectable `reclaim`/message-building shape (`lib/disk_triggers.py:137-158`) rather than adding a new trigger type.

**Simplest sufficient approach:** re-park's verify step reuses the exact same whole-folder `remote_manifest(name)` + `compare()` call first-park already does unconditionally (same O(B) cost model, no new remote script needed), instead of building a second, partial remote-hashing mechanism. The upload step targets only the changed/new relative paths via `rsync --files-from=<local tmp file>` (no `--delete`), since the local tree is now sparse (only fetched parts exist) and a whole-folder sync would tell the cold host to delete everything not present locally — this is the one genuinely new piece of logic.

**Tokens:** re-park costs nothing extra when nothing changed (diff is empty → no rsync, no remote write, straight to the swap-and-drop) — cheaper than today's silent no-op, which leaves the bytes stuck on disk forever. The low-disk guard's new hint is pure local `stat`, no network, so it adds no latency or failure mode to the preflight hot path.

**Capability, not passivity:** this fixes a real production outage (Mini stuck at 12 GB, pipeline refusing work overnight) without the owner having to hand-park sub-folders; `list`'s new local-bytes column also lets a person *see* the problem next time instead of discovering it from a stuck pipeline.

## Existing code already covers

Nothing here is already built — `lib/cold_store.py:372-375`'s `park()` really does just finish a half-done swap and return the old entry when a marker exists, with no path that re-examines local bytes. `ensure()`'s `--part` fetch (lines 578-581) is the thing that leaves bytes behind; nothing calls `park()` again afterward anywhere in the codebase (`lib/disk_triggers.py`'s `reclaim()` has four parts, none of them cold-store-aware).

## Decisions
<!-- marvin:decisions -->
### guard-mode: Should the low-disk guard (`disk_triggers.preflight`) auto-re-park, or just name parkable folders in its refusal message? (optional)
- [ ] A: Message only (my default below) — the refusal text lists local-bytes-holding folders and the `marvin-cold park PATH` command to free them, but nothing runs automatically. Zero new network dependency in the preflight hot path; a stuck cold host never slows down or risks a refusal that's already failing.
- [ ] B: Auto-run — add re-park as a fifth `reclaim()` step, same as `clean_merged_worktrees`/`download_cache.enforce_cap`, so disk is freed without a person running anything by hand. Costs an ssh round-trip (and whatever upload time) inside the preflight path, exactly when the Mac is already low on disk.

*(Implementing option A now; flip to B by adding one more `reclaim()` part if the owner prefers full automation here.)*

## Tests (written first)

Ticket's "How we'll try to break it," plus the misuse categories the ticket's own list left implicit:

1. `test_repark_after_ensure_drops_the_fetched_part_and_frees_the_disk` — park → `ensure --part SUB` → park again: part's files gone locally, marker's `parts == []`, remote manifest/entry match, **zero new rsync calls** (unchanged bytes are "sha-matched... dropped with no copy," per the ticket's own wording).
2. `test_repark_keeps_a_file_changed_locally_after_ensure` — same, but edit a fetched file's bytes before the second `park()`: the new content lands on the cold host, `manifest_sha256` changes, and a later `ensure()` returns the *new* bytes, never the old ones. (Ticket's attack #1.)
3. `test_repark_interrupted_halfway_is_finished_by_the_next_call` — kill the upload mid-way (reusing the `COPY_STOPPED` rsync-wrapper trick already in the file): nothing local lost, a second `park()` call finishes it. (Attack #2.)
4. `test_repark_of_a_folder_in_use_is_refused_and_nothing_moves` — `in_use` returns a hit: `BUSY`, nothing moved. (Attack #3.)
5. `test_a_repark_manifest_mismatch_on_the_cold_host_stops_and_keeps_local_data` — tamper the remote manifest's sha before re-park: `VERIFY_FAILED`, local untouched, nothing uploaded. (Attack #4.)
6. `test_repark_corruption_in_transit_is_caught_and_repaired` / `test_repark_corruption_that_keeps_happening_fails_and_keeps_the_local_copy` — mirrors the two existing first-park corruption tests, for the re-park upload path (one-shot `--checksum` repair, then give up without deleting).
7. `test_repark_a_folder_written_to_during_the_repark_is_not_deleted` — a late write lands mid-upload: `BUSY`, nothing swapped.
8. `test_a_file_written_next_to_the_marker_outside_any_ensure_part_is_repacked_too` — covers the bug report's "or files written next to the marker": a brand-new file dropped directly into an already-parked folder (never fetched via `--part`) gets picked up and uploaded by the next `park()`.
9. `test_list_shows_local_bytes_for_a_partially_fetched_entry` — `list`/`listing()` reports nonzero `local_bytes` after a part-fetch, zero after a re-park. (Acceptance criterion.)
10. `test_repark_with_a_concurrent_second_caller_only_reparks_once` — two threads calling `park()` on the same partially-fetched folder serialize through the existing per-name lock, one winner, consistent end state. (Repeats/concurrency misuse.)
11. `test_repark_when_the_cold_host_goes_unreachable_mid_way_changes_nothing_local` — the fake-ssh `DOWN` flag during re-park: `UNREACHABLE`, local untouched. (Dependency failure.)
12. `test_repark_of_a_folder_whose_marker_json_is_malformed_falls_back_to_a_fresh_park` — hand-corrupted `.marvin-cold.json`: `marker()` already returns `None`, so `park()` degrades to treating it as an ordinary unparked folder rather than crashing. (Stale/bad local state, a person's mistake.)
13. CLI: `test_the_cli_then_park_runs_the_job_and_reparks_when_it_ends`, `test_the_cli_then_park_still_reparks_when_the_wrapped_job_fails` (disk freed even on a failing job — exit code is the job's, not park's), `test_then_park_on_a_plain_never_parked_folder_runs_the_job_but_does_not_park_it` (guards against surprise-parking an arbitrary folder just because `--then-park` was passed).
14. `disk_triggers`: `test_preflight_refusal_mentions_a_parkable_folder_with_local_bytes` (injected hint callable, mirroring the existing `free=`/`reclaim=` DI style), `test_preflight_refusal_hint_is_silent_when_cold_store_cannot_be_read` (fails open, never blocks, no hang), `test_the_real_parkable_hint_names_a_folder_with_local_bytes_with_no_network_call` (real function against a `cold_store.Store` fixture, asserting the fake ssh log stays empty).

## Task List

1. `lib/cold_store.py`: add `_repark(path, existing)` — lock, re-check marker/local under the lock, `in_use` refusal, `_trusted_manifest` sha-check, diff `local_manifest(path)` against the trusted manifest (changed = size/hash/link-target mismatch, or absent from trusted), build the merged `new_manifest`/`new_entry`.
2. `lib/cold_store.py`: targeted upload of just the changed relative paths via `rsync --files-from=<local tmp file>` (no `--delete`), one `--checksum` repair retry on mismatch, verified with the existing `remote_manifest(name)` + `compare()` — raise `VERIFY_FAILED` with nothing deleted if it still doesn't match.
3. `lib/cold_store.py`: write the new `manifest.json`/`entry.json` remotely, re-check `stat_snapshot`/`in_use` haven't changed since the start (same ordering as first `park`), then reuse `_swap(path, new_entry)` to atomically fold the mixed folder into a clean marker and drop the local bytes; update the local catalog.
4. `lib/cold_store.py`: wire `park()`'s existing-marker branch to call `_repark` when `local_manifest(path)` is non-empty, falling back to today's "finish swap, return existing" when it's genuinely empty.
5. `lib/cold_store.py`: add `_local_bytes(path)` (cheap `stat_snapshot`-based, no hashing); extend `listing()` to attach `local_bytes` for this machine's entries with a marker present; extend `_print_listing()` to show it.
6. `lib/cold_store.py`: add `--then-park` + `command` (`argparse.REMAINDER`) to the `ensure` subparser; `main()` resolves the target once via `store._resolve(target, optional=True)` to know whether it's cold-store-managed, runs the command via `subprocess.run`, re-parks in a `finally` only if it was managed, and returns the job's exit code.
7. `lib/disk_triggers.py`: add a local-only `_parkable_hint()` (reads `cold_store.default_store()[0].catalog_all()` + `marker()` + `_local_bytes()`, no ssh), inject it into `preflight()` as a new optional parameter, append its text to the refusal message when `preflight` is below floor.
8. Add decision-point A (message-only) as the shipped default per the Decisions section above.
9. Update `lib/cold_store.py`'s module docstring (the `park:` complexity line, exit codes, Usage section) to describe re-park and `--then-park`.
10. Update `CONTEXT.md`'s "Cold store" section (`marvin#1081`) with one line on re-park and `--then-park`, dated and ticket-tagged.
11. Write the tests above in `lib/tests/test_cold_store.py` and `lib/tests/test_disk_triggers.py`, then implement 1-7 to pass them.
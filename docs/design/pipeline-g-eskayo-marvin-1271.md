I have what I need. Here's the plan.

## North-star fit

Reuses, not new-builds:
- **`_swap()` and `_write_marker()` unchanged** (`lib/cold_store.py`) — re-park's "drop what's local" step is the exact same two-rename swap first-park already does; no new deletion path to get wrong.
- **`_trusted_manifest()` unchanged** — already does the "never trust a manifest that doesn't match the marker's sha256" check (`lib/cold_store.py:492-506`); re-park calls it instead of re-deriving that logic.
- **`_remote_write()` / `_rsync()` / `self._lock()` / `in_use()` / `stat_snapshot()` unchanged** — the first-park body (`lib/cold_store.py:384-425`) already has every primitive a re-park needs (hash, lock, busy-check, race-check, atomic remote write); re-park is new glue over those, not new mechanics.
- **`test_slot.py`'s `run [--flags] -- command args...` pattern** (`lib/test_slot.py:215-241`) — reused verbatim for `ensure --then-park -- COMMAND`, instead of inventing a Python context manager for a caller that doesn't exist yet anywhere in the codebase (grep confirms nothing calls `cold_store.ensure()` outside the CLI and tests). Building a context manager now would be designing for a hypothetical caller; `--then-park` is usable from any shell job today with zero new call sites to wire up.
- **`dispatch_concurrency._safe()` and the existing `disk_free_gb`-style injected-reader pattern** (`lib/dispatch_concurrency.py:152-182`) — the "offer park" hint is one more optional injected reader (`cold_local_gb`), not a new mechanism; `ticket_pipeline.py`'s `_free_disk_gb()`/`_github_budget_pct()` (lines 762-777) is the exact style to mirror for the new `_cold_parkable_gb()`.

Simplest sufficient: the only *new* algorithmic piece is diffing "what's physically on disk now" against the trusted old manifest and uploading just the delta — done with a dict comparison already available via `local_manifest()`, not a new diff engine.

Token/compute cost: re-park is **O(bytes locally present)**, not O(bytes already safely parked) — verification of the upload is scoped to only the changed relative paths (a new `hash_selected`/`remote_hash_selected`, mirroring `build_manifest`/`remote_manifest`'s existing shipped-over-ssh pattern) rather than re-hashing the whole remote copy, which would silently reintroduce an O(B-of-everything) cost for every re-park on the exact GB-scale eval folders this ticket is about.

Phone-OS direction: marginal — this is disk hygiene plumbing, not user-facing, but it keeps the Mac mini a usable always-on node instead of one that silently fills up and refuses ticket work.

User capability: this is autonomous infra (no human workflow changes); it leaves Gil **more free** — disk no longer needs a manual half-folder cleanup (the ticket's own motivating incident: hand-parking 4 sub-folders to claw back 3 GB).

## Design (what `park()` does differently)

`park()`'s existing marker-exists branch (`lib/cold_store.py:372-375`) today does only `self._finish_swap(path); return existing`. That becomes a dispatch to a new `_repark(path, marker)`:

1. Take `self._lock(name)` (name from the marker, not re-derived).
2. Re-read the marker inside the lock; if it's gone (another caller already restored or re-parked while we waited), delegate to `self.park(path)` fresh.
3. `local_now = local_manifest(path)` (already strips marker files). If empty (nothing fetched back, or nothing left after a previous repark) → `_finish_swap`, return the marker unchanged — **identical to today's no-op**, zero rsync calls (preserves `test_park_twice_is_idempotent...`).
4. Busy check (`in_use`) → `BUSY` if refused.
5. `old = self._trusted_manifest(marker)` — validates marker's `manifest_sha256` against the stored/remote manifest; raises `VERIFY_FAILED` before touching anything if it doesn't match.
6. `changed = {kind: {rel: v for rel,v in local_now[kind].items() if old[kind].get(rel) != v} for kind in ("files","links")}` — new or content-changed paths only. Also strip any path from the *other* kind in the merged manifest (a file replaced by a symlink locally, or vice versa).
7. If `changed`: write a newline-separated rel-path list to a temp file, `rsync --files-from=<list>` (no `--delete`) up to the existing remote `data/` dir, verify with a new **scoped** remote hash (`remote_hash_selected`, hashes only the changed rels, not the whole remote tree) via `compare()`; one `--checksum` repair pass on mismatch, same as first park; still mismatched → `VERIFY_FAILED`, nothing local touched. Build `new_manifest` = old manifest with the changed entries merged in, write `manifest.json`/`entry.json` to the remote (same atomic tmp+rename `_remote_write` already used).
8. Re-check `stat_snapshot` and `in_use` right before the swap (same two-stage race guard as first park) → `BUSY` if the folder moved under us.
9. `self._swap(path, entry)` — same call first park makes; drops every local byte and writes the fresh (all-parts-gone) marker in one atomic two-rename op.
10. Only *after* the swap succeeds, `_save_catalog` the new entry+manifest. **Deliberately not before** (see below) — this is the one place I'm correcting the ticket's framing rather than copying first-park's exact order.

**Why step 10 isn't "same as first park":** first park also saves the catalog before swapping, but that's safe there because there's no pre-existing remote state to protect — a crash before the swap just leaves an untouched original folder with no marker, which `ensure`'s marker-is-ground-truth check ignores entirely. For *re*-park there **is** a pre-existing valid marker+remote state. If the catalog (and remote manifest/entry) were overwritten with the new version before the swap, and the process crashed between the remote write and the swap, the next `ensure()` or `park()` would see the *old* marker (ground truth, untouched) but find the catalog/remote now holding a mismatched new sha — `_trusted_manifest` would raise a hard `VERIFY_FAILED` on a completely healthy retry, violating "the next park or ensure finishes it, and nothing is lost." Saving the catalog only after the swap means any crash in between self-heals through `_trusted_manifest`'s existing catalog-rebuild fallback (already proven by `test_a_marker_without_its_catalog_still_fetches_and_rebuilds_the_catalog`). This is a defect in the ticket's own "same checks as a first park" framing that I'm fixing rather than reproducing.

## Other two acceptance items

- **`list` shows local bytes**: new `Store._local_bytes(path)` (walk, sum regular-file sizes, skip the two marker files) called in `listing()` for this machine's own catalog entries alongside the existing `here` field; `_print_listing` prints it when nonzero.
- **Triggers**: `ensure` gets `--then-park -- COMMAND ARGS...` (argparse `REMAINDER`, identical shape to `test_slot.py run --merge -- command`): fetches, runs the command, parks again in a `finally` regardless of the command's exit code — "a context manager" is the ticket's other offered option; I'm not building it because nothing in this codebase calls `cold_store.ensure()` as a library today, so it would be speculative. `dispatch_concurrency.can_start_another()` gets one new optional injected reader, `cold_local_gb`; when the disk guard trips, it appends how many GB `marvin-cold park` could free. `ticket_pipeline.py`'s `_select_for_profile` wires it with a new `_cold_parkable_gb()` (mirrors `_free_disk_gb`), only for `is_self`, calling `cold_store.Store.parkable_gb()` (sums `_local_bytes` across this machine's own catalog).

**No Decisions section** — nothing here needs Gil to choose between product-visible options; the two implementation forks offered by the ticket text (context-manager vs. `--then-park`) are an engineering call, not a user-facing one, and I've made it with a stated reason above.

## Tests to write first (`lib/tests/test_cold_store.py` unless noted)

From "How we'll try to break it":
1. `test_a_file_changed_locally_after_ensure_is_kept_on_repark_and_a_later_ensure_returns_it` — `ensure --part`, edit the fetched file, `park` again, assert the upload happened, assert a fresh `ensure` elsewhere returns the *new* content, not the original.
2. `test_a_repark_interrupted_after_the_remote_write_is_finished_by_the_next_park_or_ensure` — simulate a crash between `_remote_write` and `_swap` (call the pieces directly, or monkeypatch `_swap` to raise once); assert a follow-up `park()` *and* a follow-up `ensure()` both complete cleanly with no `VERIFY_FAILED`, and nothing local is lost in between.
3. `test_a_folder_with_open_files_is_refused_on_repark` — `in_use` returns a hit after a partial `ensure`; `park()` raises `BUSY`, nothing moved, remote manifest unchanged.
4. `test_a_tampered_remote_manifest_stops_a_repark_before_anything_is_dropped` — corrupt the remote `manifest.json` sha mismatch (mirror the existing `ensure`-side test but for `park`); assert `VERIFY_FAILED`, local files still present, remote files untouched.

Misuse the list didn't cover:
5. `test_repark_after_a_part_ensure_with_nothing_changed_drops_it_with_no_upload` — `ensure --part`, immediately `park` again with no edits: assert zero rsync calls (sha-matched, no copy), folder back to marker-only, manifest/entry unchanged on the remote.
6. `test_a_file_written_next_to_the_marker_is_picked_up_and_parked` — write a brand-new file directly into the parked folder (not via `ensure --part`) and park; assert it gets uploaded and dropped.
7. `test_a_file_replaced_by_a_symlink_locally_reparks_as_a_link_not_both` — stale-state/person's-mistake case; assert the merged manifest has exactly one entry for that path, under the right kind.
8. `test_repark_resumes_after_the_cold_host_goes_down_mid_upload` — mirror `test_the_cold_host_being_off_fails_calmly_and_changes_nothing` for the repark path.
9. `test_a_corrupted_reupload_is_repaired_once_then_fails_and_keeps_local_data_if_it_keeps_happening` — mirror the two existing corruption tests for the repark upload path.
10. `test_a_folder_written_to_during_a_repark_is_not_deleted` — mirror the write-during-park race test for repark.
11. `test_repark_with_many_scattered_changed_files_uploads_and_verifies_all_of_them` — ~50 changed files across several subdirectories, to exercise the `--files-from` temp-file + `remote_hash_selected` temp-file plumbing (not just a single-file happy path), since that path is specifically designed to avoid ARG_MAX and must handle more than one file.
12. `test_a_concurrent_ensure_part_and_repark_dont_corrupt_each_other` — concurrency case mirroring `test_two_ensure_calls_at_once_fetch_only_once`, but one thread doing `ensure(part=...)` and another doing `park()` on the same name.
13. `test_list_shows_local_bytes_for_a_half_fetched_entry_and_nothing_when_fully_parked` — `ensure --part`, `list`, assert nonzero `local_bytes`; full `ensure`+`park` again, `list`, assert it's back to zero/absent.
14. CLI (`test_the_cli_prints_the_path_and_returns_the_exit_code`-style, new functions): `test_then_park_runs_the_command_and_reparks_even_when_the_command_fails` (assert re-park happened after a nonzero-exit command); `test_then_park_with_no_command_is_a_clean_refusal`.

`lib/tests/test_dispatch_concurrency.py`:
15. `test_low_disk_offers_a_park_hint_when_cold_local_gb_is_available` — `can_start_another(..., cold_local_gb=lambda: 3.2)` on a disk-low refusal includes the GB figure; omitted when `cold_local_gb` is `None` or returns falsy.
16. `test_an_unreadable_cold_local_gb_reader_does_not_crash_or_block` — `cold_local_gb=boom` still returns the plain disk-low refusal, no exception, no hint.

(`lib/tests/test_ticket_pipeline.py`, if `_select_for_profile`'s guard wiring has existing coverage worth extending — to confirm, if I were implementing: check whether that file already tests `can_start_another`'s call site and extend it for `is_self` vs not.)

## Task List

1. `lib/cold_store.py`: add `hash_selected(folder, rels)` (self-contained, mirrors `build_manifest`'s shipped-over-ssh style) + `REMOTE_HASH_SELECTED_PY` + `Store.remote_hash_selected(name, rels)` (writes a temp rels-list file remotely via `_remote_write`, runs the script, removes the temp file).
2. `lib/cold_store.py`: add `Store._local_bytes(path)` and `Store.parkable_gb()`.
3. `lib/cold_store.py`: add `Store._repark(path, marker)` implementing the flow above (lock → empty-check/no-op → busy → trusted old manifest → diff → targeted upload+verify+repair → remote manifest/entry rewrite → race re-check → swap → catalog save after swap).
4. `lib/cold_store.py`: change `park()`'s marker-exists branch (`lib/cold_store.py:372-375`) to call `_repark` instead of the bare finish-swap-and-return.
5. `lib/cold_store.py`: `listing()` — add `local_bytes` alongside `here` for this machine's catalog entries; `_print_listing` — show it when nonzero.
6. `lib/cold_store.py`: CLI — add `--then-park` + `command` (`REMAINDER`) to the `ensure` subparser; `main()` — when `--then-park`, run the command after `ensure` and call `store.park(...)` in a `finally`, regardless of the command's exit code; clean refusal when no command follows `--`.
7. `lib/cold_store.py`: update the module docstring (park's complexity note, usage line) to describe re-park and `--then-park`.
8. `lib/dispatch_concurrency.py`: add optional `cold_local_gb` reader param to `can_start_another`; append the hint to the disk-low refusal reason via the existing `_safe()` wrapper.
9. `lib/ticket_pipeline.py`: add `_cold_parkable_gb()` (mirrors `_free_disk_gb`); wire it into `_select_for_profile`'s `can_start_another` call as `cold_local_gb=(lambda: _cold_parkable_gb()) if is_self else None`.
10. Write all 16 tests above, confirm the full existing `test_cold_store.py` and `test_dispatch_concurrency.py` suites still pass unmodified (especially the idempotent-double-park and no-marker-matched regression tests), then the new ones.
11. Update `CONTEXT.md`'s Cold store section (`CONTEXT.md:2050-2062`) to mention re-park and `--then-park`, consistent with how that section already documents `ensure`.
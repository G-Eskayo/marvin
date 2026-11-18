1. `lib/cleanup_sweep.py`: add `_default_has_live_task(repo, number)` backed by `dispatch_concurrency.slots_in_use()`.
2. `lib/cleanup_sweep.py`: rename `decide_worktree`'s `claimed` param → `live_task`; rename `sweep_worktrees`'s `is_claimed` param → `has_live_task` (default `_default_has_live_task`); move its call into the existing GH try/except with its own review message.
3. `lib/cleanup_sweep.py`: change `EMPTY_MIN_AGE_HOURS` 24 → 2, update its comment.
4. `lib/cleanup_sweep.py`: fix `_list_root()` to surface detached-HEAD and missing-`.git` worktrees for review instead of silently skipping them; update `sweep_worktrees()` to route the new shapes to "review" like the existing `broken` case.
5. `lib/disk_trim.py`: update `_build_never_trim_worktrees()`'s call site to `cs._default_has_live_task`.
6. `lib/disk_triggers.py`: add `_orphan_worktrees_step()` and wire it into `reclaim()`'s `parts` list (respecting `cs._is_pull_only()` for `can_push`).
7. `lib/purpose_metrics.py`: add `_orphan_pipeline_worktrees()` (scoped to `cs.WORKTREES_ROOT` only) and register it in `PROBES` as `orphan-pipeline-worktrees` (limit 2.0).
8. Update existing tests in `lib/tests/test_cleanup_sweep.py`, `test_disk_trim.py`, `test_disk_triggers.py` for the renamed params (`claimed=`/`is_claimed=` → `live_task=`/`has_live_task=`).
9. Add the 15 new/updated tests listed above across `test_cleanup_sweep.py`, `test_disk_trim.py`, `test_disk_triggers.py`, `test_purpose_metrics.py`.
10. Commit the design doc (this plan, trimmed) inside the ticket's own worktree/branch per the existing "Ticket design doc / task list" convention — not into `CONTEXT.md`.
11. Resolve the Decisions item above (or carry it into the PR for the owner) before/at PR time.
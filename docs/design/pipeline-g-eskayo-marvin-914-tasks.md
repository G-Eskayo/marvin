1. `lib/cleanup_sweep.py`: add `_default_has_live_task`; rewire `decide_worktree`'s third parameter and `sweep_worktrees`'s `is_claimed`→`has_live_task` param (split try/except for GitHub vs. local-task failures); propagate the rename through `run_daily_sweep`.
2. `lib/cleanup_sweep.py`: switch `_default_list_worktrees`/`_list_root`'s `in_use` detection from `_cwds_in_use()` to `_open_paths()` (add `open_paths` injection param; `None` → fail-safe `in_use=True`).
3. `lib/cleanup_sweep.py`: fix the two silent `continue`s in `_list_root` (detached HEAD, missing `.git`) to report `broken: True` instead of disappearing.
4. `lib/disk_triggers.py`: add `clean_empty_worktrees()` (locked, sized wrapper around `cs.sweep_worktrees`) and add it to `reclaim()`'s parts list.
5. `lib/disk_trim.py` and `lib/disk_reclaim.py`: swap `cs._default_is_claimed` → `cs._default_has_live_task` at their `decide_worktree` call sites.
6. `lib/purpose_metrics.py`: add `_orphan_pipeline_worktrees()` and register it in `PROBES` as `"orphan-pipeline-worktrees"`.
7. `lib/tests/test_cleanup_sweep.py`: update existing `claimed=`/`is_claimed=` call sites to `has_live_task=`; add tests 1, 5, 6, 8, 9, 11, 12 above.
8. `lib/tests/test_disk_triggers.py`: add tests 10, 11 (reclaim-level) above, modeled on the existing `clear_rebuildable` lock/sizing tests.
9. `lib/tests/test_pull_only_node.py`: rename its three `is_claimed=` keyword calls to `has_live_task=`.
10. `lib/tests/test_purpose_metrics.py`: add test 13 above for the new probe.
11. Run the full Python suite (not just the touched files) before considering this done, per the full-suites-before-merge standard.
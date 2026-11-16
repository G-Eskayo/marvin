## North-star fit

**Reuses:** `lib/cleanup_sweep.py:decide_worktree` (already the general "no PR, no commits, clean, old → remove" rule, added for #629/#866) and `lib/disk_triggers.py:reclaim`/`clear_rebuildable`'s self-contained, non-blocking `fcntl.flock` single-flight pattern (lines 795–810). No new worktree-decision machinery — the fix changes which *signal* `decide_worktree` treats as "still running," not the decision tree itself.

**Simplest sufficient approach:** The general "empty attempt" removal path already exists and already runs daily. The 23-worktree pileup isn't a missing rule, it's a wrong signal: `decide_worktree`'s `claimed` check reads the GitHub `claimed:*` label via `_default_is_claimed`, and `ticket_policy.stale_claim` (the only thing that clears that label) measures idleness from the issue's `updatedAt` — which every retry-backoff comment (`marvin:retry-after`) bumps. A ticket retried every 15 min–4 h therefore never accumulates 6–24 h of GitHub-visible quiet time, so the label never clears and `decide_worktree` keeps "protecting" a worktree with no process anywhere near it. `dispatch_concurrency.slots_in_use()` is immune to this: it's reaped the instant the PID dies, independent of GitHub comment traffic. Swapping that one signal, plus widening the "nothing has this worktree open" check from cwd-only (`_cwds_in_use`) to full open-file handles (the existing `_open_paths()`, already used by `trim_pytest_temps`), closes the gap with no new abstractions.

**Tokens:** spends a few extra local JSON reads per worktree per sweep (cheap, no network); saves disk and, per the ticket, unblocks the Mini's build floor.

**More capable, not more passive:** this is pure infrastructure upkeep the owner explicitly asked to stop doing by hand (he removed the 23 manually on 2026-10-30); automating it returns that time with no change to what Gil sees or decides.

**ADR check:** ADR 0065's table lists "worktrees with no PR" under **Irreplaceable** ("never deleted automatically"). The shipped `decide_worktree` already narrows that for the case of **no PR *and* no commits ahead *and* clean** — exactly ADR 0065's own test ("everything worth keeping is already saved elsewhere") — which this ticket extends, not contradicts. The ADR's one-line table entry is an over-generalization the code has already refined twice (#629, #866); I'll leave the ADR text as is (not in scope) but flag it rather than silently build around it.

## What's actually missing (root cause, verified against the code)

1. `decide_worktree`'s "claimed" input is sourced from the sticky GitHub label, not a live-process check → the actual bug.
2. `disk_triggers.reclaim()` only calls `clean_merged_worktrees` (merged-PR worktrees) — it never runs the general empty-attempt rule at all, so a worktree that will eventually be swept daily gets no help from the low-disk trigger.
3. `_in_use` for the general sweep is cwd-only (`lsof -d cwd`), not full open-file handles.
4. Two silent `continue`s in `cleanup_sweep._list_root` (detached HEAD; a folder with no `.git` at all) make those worktrees invisible to review forever — contradicts the module's own "silent failure is the recurring real problem" docstring.
5. Three other call sites (`disk_trim._build_never_trim_worktrees`, `disk_reclaim`'s re-check) independently recompute the same stale "claimed" boolean and feed it into `decide_worktree` — left on the old signal they'd still be safe (over-conservative) but inconsistent with the fixed definition.

## Changes

**`lib/cleanup_sweep.py`**
- Add `_default_has_live_task(repo, number) -> bool`: calls `dispatch_concurrency.slots_in_use()` (local, no machine filter needed — `TASKS_DIR` is already per-machine) and checks for an alive record with matching `repo` and `str(ticket) == str(number)`.
- `decide_worktree(wt, pr_state, has_live_task)`: rename the third parameter's meaning (keep the function/branch structure; only the "its ticket is claimed (running)" branch's input and message change — now "a task is running for it").
- `sweep_worktrees(...)`: rename `is_claimed` param → `has_live_task`, default to `_default_has_live_task`; split the existing single try/except (which currently conflates GitHub and claim lookups) into two — `pr_state` failures still report "could not check GitHub" (unchanged, satisfies "#880" requirement), `has_live_task` failures report "could not check for a live task" and default to *not* removing (fail toward keeping).
- `run_daily_sweep(...)`: rename its `is_claimed` passthrough param → `has_live_task` (mechanical propagation).
- `_default_list_worktrees()` / `_list_root()`: switch the `in_use` computation from `_cwds_in_use()` to the existing `_open_paths()` (superset of cwd; already fails safe — `None` → nothing removed). Add an injectable `open_paths` parameter to `_default_list_worktrees` for testability, mirroring `trim_pytest_temps(open_paths=...)`.
- `_list_root()`: stop silently `continue`-ing on a detached HEAD or a missing `.git`; report both as `{"path": entry, "broken": True}` (same bucket `sweep_worktrees` already routes to "review", never to removal) — simplifies the branching too (one condition instead of two).

**`lib/disk_triggers.py`**
- Add `clean_empty_worktrees()`: single-flight guarded with `cs.LOCK_PATH` (identical non-blocking `fcntl.flock` idiom as `cs.clear_rebuildable`), calls `cs.sweep_worktrees()` with a sized `remove_worktree` wrapper (measuring via the existing `_size_bytes`, same as `clean_merged_worktrees` already does) so freed bytes are reportable.
- `reclaim()`: add `("empty worktrees", clean_empty_worktrees)` to its `parts` list, alongside the existing three.

**`lib/disk_trim.py`, `lib/disk_reclaim.py`**
- One-line swap each: `cs._default_is_claimed(...)` → `cs._default_has_live_task(...)`, so "keep/review" decisions for build-output trimming and manual reclaim stay consistent with the fixed definition.

**`lib/purpose_metrics.py`**
- Add `_orphan_pipeline_worktrees() -> float`: reuses `cs._default_list_worktrees()` + `cs._extract_issue_number` + `cs._default_has_live_task`, filtered to paths under `sandbox_orchestration.WORKTREES_ROOT` (imported into `cleanup_sweep` as `cs.WORKTREES_ROOT`), counting entries that are not broken/detached, not in use, not dirty, not ahead, have no live task, and `age_hours >= 2`. Matches the ticket's probe spec literally (no PR-state condition stated, so none added).
- Register `"orphan-pipeline-worktrees": (lambda days=PROBE_WINDOW_DAYS: _orphan_pipeline_worktrees(), 2.0, "pipeline worktrees clean, even with main, no live task, idle 2h+ (#914)")` in `PROBES`.

## Tests first (one per "How we'll try to break it" item, plus the missed cases)

1. **Run still going, task record not yet written** — reuse/confirm existing `test_a_ticket_that_just_started_is_not_mistaken_for_empty` still passes once `claimed` param is renamed; add a variant where `has_live_task=False` but `age_hours` is low → kept ("new, may be a ticket starting"), proving the age gate (not the live-task flag) is what protects a just-claimed, not-yet-started run.
2. **PR closed without merging but with commits** — confirm existing `test_resolved_pr_is_removed` (parametrized `CLOSED`, `ahead=1`) still removes (lossless: branch keeps the commits). No behavior change expected; locks in current behavior under the new signature.
3. **Dirty worktree** — confirm existing `test_uncommitted_work_is_backed_up_never_plainly_removed_even_when_merged` unaffected by the rename.
4. **Branch ahead with no PR** — confirm existing `test_commits_without_a_pr_are_backed_up` unaffected.
5. **Wrong permissions / each dependency failing** — new: `has_live_task` raising (e.g. `TASKS_DIR` unreadable, malformed JSON) → worktree goes to "review" with "could not check for a live task", never removed, and the *other* worktrees in the same sweep still process normally.
6. **Detached HEAD** — new: a worktree whose `git branch --show-current` is empty is reported under review (`"broken"`), never silently skipped, never removed.
7. **GitHub unreachable** — new: `pr_state` raising → "review: could not check GitHub" (unchanged contract, re-verify after the try/except split), and confirm `has_live_task` is never even consulted in that branch.
8. **A worktree a Claude session has open** — existing cwd-based coverage (`test_a_process_inside_a_clean_merged_worktree_keeps_it`-style) stays green; new test: a process with an open file handle inside the worktree whose **cwd is elsewhere** still marks it `in_use` (requires the `_open_paths` injection point) — this is the case cwd-only checking missed.
9. **Missing `.git` file** — new: a plain directory with no `.git` under a worktree root is reported for review, not silently ignored and not force-removed.
10. **Two sweeps at once** — new: `dt.clean_empty_worktrees()` called while `cs.LOCK_PATH` is externally held (same pattern as `test_clear_rebuildable_waits_for_nobody_when_the_sweep_is_running`) returns `{"changed": False, ...}` and touches nothing.
11. **Core rule, true positive** — new: a worktree with no live task (`dispatch_concurrency.slots_in_use()` returns no matching record), no PR, no commits ahead, clean, age > grace → removed by `sweep_worktrees`, and the same scenario via `dt.clean_empty_worktrees()` from `reclaim()` reports nonzero `freed_bytes`.
12. **Stale GitHub label, no live process (the actual #914 bug)** — new, most important: `claimed:*` label present (simulate via a stub that would have returned `True` under the old `is_claimed` signal) but `dispatch_concurrency.slots_in_use()` has no matching record → removed. This is the regression test that would have failed before this fix.
13. **Probe correctness** — new: `purpose_metrics._orphan_pipeline_worktrees()` counts only worktrees under `WORKTREES_ROOT`, excludes dirty/ahead/in-use/live-task/broken/age<2h, over a fixture with one real orphan and five near-misses (one of each excluded reason).
14. **disk_trim / disk_reclaim consistency** — confirm `_build_never_trim_worktrees` (disk_trim.py) and disk_reclaim's re-check still call through to `_default_has_live_task` and produce the same "keep/review" set as before for an actively-claimed-and-running worktree (no regression in build-output protection).

## Decisions

None. The ticket is fully specified: the signal to use (`dispatch_concurrency.slots_in_use`), the two places to wire it (cleanup sweep, low-disk trigger), and the fallback (no GitHub token → keep) are all stated, and nothing in the codebase contradicts them in a way that needs the owner's input.

## Task List

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
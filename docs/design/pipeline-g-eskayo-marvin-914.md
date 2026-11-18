## North-star fit

**Reuses:** `lib/cleanup_sweep.py`'s `decide_worktree()`/`sweep_worktrees()` (the one function that already decides "remove / backup / keep / review" for every pipeline worktree, built 2026-10-06 for #9 and extended by #629/#866) and `lib/dispatch_concurrency.py`'s `slots_in_use()` (the existing, already-tested local task-liveness primitive task-dispatch itself relies on). No new removal mechanism, no new worktree enumeration — one existing decision function gets one input swapped, and gets called from a second call site (`disk_triggers.reclaim()`) it wasn't wired into yet.

**Why simplest sufficient:** traced the actual 2026-10-30 incident through the code (not guessed): `run_ticket.py`'s `_release_claim()` releases the `claimed:<machine>` label at the end of *every* run, win or lose — so the label isn't the thing getting stuck. What's stuck is the **age gate**: `decide_worktree()`'s "empty attempt" branch only fires once the worktree directory's own mtime is ≥ `EMPTY_MIN_AGE_HOURS` (24h), and a ticket retried every 15–120 min (the verify-timeout backoff visible in #914's own comments) keeps touching that same reused worktree, so the 24h clock never completes while the retry storm runs. The ticket's own recurrence-check probe spec ("clean, even with main, no live task, older than 2h") is the fix already written down: swap the slow, retry-resettable mtime-age signal for the instant, non-resettable one (`dispatch_concurrency.slots_in_use()`, written before the worktree is ever touched — confirmed in `task_dispatch._build_wrapper_script`) and shrink the grace window from 24h to 2h, which is still orders of magnitude larger than the real race (sub-second to a few seconds between `_claim()` and the dispatched script's first line).

**Where it spends/saves tokens:** no model calls in any of this — pure deterministic Python, same as the rest of `cleanup_sweep.py`/`disk_triggers.py`. Net effect is fewer wasted tokens long-term: orphaned worktrees were the thing silently eating 16 GB and, per #914's own text, blocking builds under the 15 GB floor (`dispatch_concurrency`'s `min_disk_gb` guard), which otherwise stalls dispatch outright.

**Phone-OS direction:** N/A directly — this is a resource-hygiene fix on one machine (Mac mini), not a reachability/general-capability change.

**Capability vs passivity:** purely infrastructural; no user-facing behavior changes, so this axis doesn't really apply. It does remove a recurring manual chore (Gil hand-checking and deleting worktrees, as he did by hand on 2026-10-30).

**Runs on:** both Macs (cleanup_sweep is scheduled on both; disk_triggers.preflight runs wherever a helper/dispatch starts) — same as today, no machine-placement change.

**Correction to the ticket's own "What happened":** it attributes the leak to "no PR ever merged," but `decide_worktree()` already has an empty-attempt/no-PR removal path since 2026-10-06. The actual defect is the age-gate being reset by the retry cadence, not the absence of a general rule — the fix below still produces the general rule the ticket asks for, just via the real mechanism.

---

## Design

### Root cause (traced, not assumed)
- `ticket_pipeline.py` claims before dispatch, dispatch's wrapper script writes its task record (`~/.claude/dispatch/tasks/<id>.json`, with `ticket`/`repo`/`pid`) *before* `run_ticket.py` ever touches the worktree, and `run_ticket.py`'s `_release_claim()` releases the GitHub `claimed:<machine>` label at the end of every run — so neither signal is the one that gets stuck.
- `decide_worktree()`'s final branch only removes a clean, PR-less, not-ahead worktree once its **directory mtime** is ≥ `EMPTY_MIN_AGE_HOURS` (24h). A worktree reused across a fast retry loop (15–120 min backoff, per #536/#881's verify timeouts) keeps getting touched, so it never reaches 24h of quiet while the storm runs, even though it is provably idle *between* each retry.
- Separately, two silent gaps found in `_list_root()` (`lib/cleanup_sweep.py:151-178`): a worktree with a **detached HEAD** (`git branch --show-current` empty) and one with a **missing `.git`** (no file/dir, not even an orphaned one) are both just `continue`d past — never removed, never listed for review. Both are explicitly in the ticket's "how we'll try to break it" list and are real, present bugs (north star 2: nothing breaks silently).

### Changes

**`lib/cleanup_sweep.py`**
- Add `_default_has_live_task(repo, number) -> bool`: checks `dispatch_concurrency.slots_in_use()` (no `machine` filter — a worktree only ever exists on the machine that owns its task record) for a record where `str(rec.get("ticket")) == str(number) and rec.get("repo") == repo`. Pure local file/PID read, no network, so it can never misread a GitHub outage as "no task."
- `decide_worktree(wt, pr_state, live_task)`: rename the 3rd param `claimed` → `live_task`; same branch structure, reworded "keep" reason ("a build is running for this ticket right now").
- `sweep_worktrees(...)`: rename `is_claimed` param → `has_live_task` (default `_default_has_live_task`); move its call inside the existing try/except used for `pr_state`, with its own "could not check for a live task: …" review reason (mirrors the existing "could not check GitHub" pattern) so a broken/unreadable `TASKS_DIR` (wrong permissions) degrades to "review", never a crash or a silent removal.
- `EMPTY_MIN_AGE_HOURS`: `24` → `2`, matching the ticket's own recurrence-check probe definition; comment updated to explain it now guards only the claim→dispatch race (seconds), not claim staleness (which `live_task` now covers directly).
- `_list_root()`: stop silently dropping detached-HEAD and missing-`.git` worktrees — append them (e.g. `{"path": entry, "broken": True, "reason": "detached HEAD"}` / `"no .git file or directory"`), routed to "review" the same way the existing orphaned-metadata case already is.

**`lib/disk_trim.py`** (`_build_never_trim_worktrees`, line 64) — swap `cs._default_is_claimed(repo, number)` for `cs._default_has_live_task(repo, number)` to match the renamed `decide_worktree` signature; this is the third real call site (besides `sweep_worktrees` itself) and must move together or it breaks.

**`lib/disk_triggers.py`** — `reclaim()` currently only removes *merged*-PR worktrees (`clean_merged_worktrees`); it never ran the general empty-attempt rule, which is the literal gap in "disk_triggers after-merge and cleanup_sweep remove worktrees whose PR merged… a run without a PR never gets cleaned" for the *low-disk* path specifically. Add a new part:
```python
("orphaned worktrees", lambda: _orphan_worktrees_step()),
```
`_orphan_worktrees_step()` calls `cs.sweep_worktrees(can_push=not cs._is_pull_only())` (respecting ADR 0069's pull-only nodes, same as the daily sweep) and reports `{"freed_bytes": 0, "detail": "removed N orphaned worktree(s) …"}` — no byte accounting, matching the daily sweep's own existing worktree-removal logging convention (it doesn't measure worktree size either).

**`lib/purpose_metrics.py`** — add the ticket's own named probe:
```python
def _orphan_pipeline_worktrees(min_age_hours: float | None = None) -> float:
    ...  # cs._list_root(cs.WORKTREES_ROOT, cwds) only (not helper worktrees) -- the probe's own literal scope
```
counting worktrees that are clean, even with main (`ahead` falsy), not `in_use`, have no live task (`cs._default_has_live_task`), and are older than `cs.EMPTY_MIN_AGE_HOURS` (reused, not a second hardcoded `2.0`). Registered in `PROBES`:
```python
"orphan-pipeline-worktrees": (lambda days=PROBE_WINDOW_DAYS: _orphan_pipeline_worktrees(), 2.0,
                              "pipeline worktrees clean, even with main, no live task, older than 2h (#914)"),
```

**Not touched:** `lib/disk_reclaim.py` — found it also calls `decide_worktree(wt, state, claimed)` (line 230), but it's dead code from the unrelated, already-merged #130 (never scheduled, no caller, no test, and already broken today — it checks `action in ("clean", "archive")`, values `decide_worktree` never returns, so it already never deletes a real worktree). Left alone; see Decisions below.

### Tests (written first)

From "How we'll try to break it":
1. Run still going, task record not written yet → `live_task` reader not yet reporting it, worktree `age_hours` just under the new 2h threshold → `decide_worktree` returns **keep**, not remove (race protection).
2. Closed-without-merge PR *with* commits ahead → still **remove** (existing short-circuit before the `ahead` check; branch stays reachable) — regression check after the param rename.
3. Dirty worktree → **backup**/**review** per existing age rule — regression check.
4. Branch ahead of main, no PR → **backup**/**review** per `BACKUP_MIN_AGE_HOURS` — regression check.
5. Detached HEAD → currently silently invisible; after the fix, appears in **review**, never removed, never crashes `_list_root`.
6. GitHub unreachable (pr_state raises) → **review**, "could not check GitHub…", even though the (local) live-task check succeeds — regression check that removing GH from the liveness check didn't change this contract.
7. A live Claude session has the worktree open (`lsof` cwd match) → **keep**, "a process is working inside it" — regression check, unaffected by the rename.
8. Missing `.git` (no file or dir at all) → currently silently invisible; after the fix, appears in **review**, not dropped.
9. Two sweeps/reclaims at once → both call `git worktree remove` on the same path; the loser gets git's own nonzero exit → logged as "review"/"git refused", no crash, no partial deletion (git's atomicity, not new locking) — test asserts no exception and no double free.
10. `dispatch_concurrency.slots_in_use()` raising (e.g. `TASKS_DIR` unreadable — permissions) → `_default_has_live_task` must not propagate; caught by `sweep_worktrees`'s try/except → **review**, "could not check for a live task: …", never a silent removal.
11. Malformed/renamed branch with no parseable issue number → `number is None` → `has_live_task` short-circuits to `False` without calling the reader → falls through to the existing dirty/ahead/PR checks unchanged.
12. `disk_triggers.reclaim()` wired to the new step: a worktree that's merged-PR-removed by `clean_merged_worktrees()` in the same `reclaim()` call is simply absent from the follow-up `sweep_worktrees()` listing — no double-removal attempt, no crash.
13. Pull-only node (ADR 0069) calling `reclaim()` → `_orphan_worktrees_step()` passes `can_push=False`; a dirty/ahead worktree there is kept (never backed-up-and-pushed from an untrusted box), matching `run_daily_sweep`'s existing pull-only behavior.
14. Probe (`orphan-pipeline-worktrees`): scoped only to `WORKTREES_ROOT` (not `.claude/worktrees` helper trees); a worktree with `ahead>0` or `dirty` or `in_use` or a live task or age `< EMPTY_MIN_AGE_HOURS` is excluded from the count; one genuinely orphaned worktree is counted.
15. `disk_trim.py`'s `_build_never_trim_worktrees()` after the rename: a worktree with a live task is still added to `NEVER_TRIM` (regression — build output under a running ticket's worktree must never be trimmed).

## Decisions

<!-- marvin:decisions -->
### fix_disk_reclaim: `lib/disk_reclaim.py` (dead code from #130) calls `decide_worktree()` with a signature it already misuses (checks for return values `"clean"`/`"archive"` that don't exist, so it has never actually protected or deleted a worktree) — found while touching this exact function. It's unused: no scheduler, no caller, no test file.
- [ ] A: Leave it untouched — out of scope for #914, revisit separately if it's ever wired in
- [ ] B: Fix its `decide_worktree()` call and return-value check now, while I'm already changing that function's signature
- [ ] C: Delete it now (unused, broken, and duplicates `disk_trim`'s + `cleanup_sweep`'s existing candidate logic)

## Task List

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
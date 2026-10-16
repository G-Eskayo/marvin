## North-star fit

Reuses what's already in the tree without redesigning it: `refresh(state_path, head, run_suite, now, repo_dir, lock_path, changed_paths)` is still the one entry point, the lock file lives beside the state file (`lock_path or Path(state_path).parent / "main-health.lock"`), the skip-path constant and `carried`/`tested_sha` plumbing through `check_main_health()` and `boot_data.js testLine()` are already correct and already tested. I read all of `lib/main_health.py`, `lib/health_checks.py`'s `check_main_health`, `dashboard/electron/main/boot_data.js`, and `lib/tests/test_main_health.py` in full before writing this: the carry-sha bug and the `LOCK_DIR`-touches-real-home bug from the *previous* review round are both already fixed in the current working tree (uncommitted). `CONTEXT.md`'s diff is accurate and carries no stray ADR citation (grepped — no "0062" anywhere in `lib/main_health.py`, `CONTEXT.md`, or the dashboard files). So this attempt is scoped purely to the five remaining must-fix findings from the latest code review; nothing upstream of them needs to change.

Simplest sufficient approach: every fix is a few lines inside functions that already exist (`_acquire_lock`, `_is_stale`) or test bodies that already exist — no new module, no new abstraction. The lock-takeover fix in particular reduces to *trusting the kernel*: `O_CREAT|O_EXCL` already gives atomic single-winner semantics for the fresh-lock case; applying the same primitive to the takeover case (unlink the stale lock, then retry the exact same exclusive-create call) removes the race without adding any new locking primitive.

Token cost: small and bounded — one real code fix (`_acquire_lock`), one real code fix (`_is_stale` determinism), and five test fixes, each addressing exactly one named finding, no speculative hardening beyond what review flagged. No re-litigation of carry-sha, LOCK_DIR, PID-match-on-release, or dashboard wiring — those already passed review and stay untouched.

Leaves the user more capable: closes the actual gap that let two refreshers both think they'd won a stale lock and both run 5.5-minute suites concurrently — the literal production incident (2026-10-15, three concurrent `main_health.py refresh` runs starving the merge gate) this ticket exists to prevent.

## Decisions

None needed. Every fix below has one correct answer forced by the existing code shape, the review's own stated fix, or the ticket text; none is a style/taste call for the owner.

## What's already correct (verified against the current working tree, not re-tested)

- Carry branch sets `sha`/`tested_sha` explicitly (`main_health.py:169`) — fixed already.
- `lock_path` defaults to `Path(state_path).parent / "main-health.lock"`, no `LOCK_DIR` home-anchored constant — fixed already.
- `run_suite()` exception path returns `{**prior, "ran": False}` inside `finally: _release_lock(...)` — fixed already.
- `_changed_paths` uses two-dot `git diff --name-only old new` (two positional args, not `old...new`) — fixed already.
- `_pid_alive` catches `PermissionError` separately and returns `True` — fixed already (only the *test* proving it is missing, see below).
- `_release_lock` re-reads and only unlinks if the PID inside still matches `os.getpid()` — fixed already.
- `CONTEXT.md` and `main_health.py`'s docstring carry no ADR 0062 citation — nothing to remove.
- `dashboard/electron/main/boot_data.js` `testLine()` already renders `· CARRIED FROM <sha>` from `main:green`'s detail string, and `check_main_health()` already appends `(carried from {tested_sha})` — both already tested in `boot_data.test.js` and `test_health_checks.py`. Not touched.

## What's still broken (confirmed by re-reading the code, matching the review exactly)

1. **`_acquire_lock` (main_health.py:80-116) is still check-then-`os.replace`**, not single-flight. Two callers can both read a dead/stale lock, both decide "takeover possible," and both `os.replace()` their own payload in — last writer wins, but *both* `_acquire_lock()` calls return `True`, so both run the suite concurrently. This is the exact finding; nothing about it changed between review rounds.
2. **Four tests touch the real `~/.agents` via an uninjected `_changed_paths`**: `test_lock_survives_killed_run`, `test_run_suite_exception_returns_prior`, `test_run_suite_exception_releases_lock`, `test_cannot_acquire_lock_returns_prior` all move the head sha without passing `changed_paths=`, so `refresh()`'s carry check calls the real `_changed_paths(REPO_DIR, tested_sha, sha)` — a real `git diff` subprocess against the user's actual `~/.agents` checkout — and only "passes" because the bogus shas make that diff fail and return `None`.
3. **`test_pid_alive_returns_true_for_permission_error` doesn't test the `PermissionError` branch at all** — it calls `_pid_alive(os.getpid())`, which exercises the `os.kill(pid, 0)` success path, not the `except PermissionError` path. The code is already correct; the test proves nothing.
4. **`test_changed_paths_uses_two_dot_diff`'s force-push scenario doesn't actually create a two-dot/three-dot divergence.** `git reset --hard HEAD~1` moves the branch pointer back to sha2, then commit4 is a direct child of sha2 — so sha4 is a straight-line descendant of sha2 and `sha2...sha4` (merge-base diff) and `sha2 sha4` (tree diff) are identical. The assertion `"file4.txt" in paths` passes under *either* behavior, so the test can't fail even if the two-dot fix were reverted.
5. **`test_is_stale_includes_worktree_setup_timeout`'s "exactly at the boundary" case is flaky by construction.** It computes `now_ts` once, then calls `mh._is_stale(at_total)`, which internally calls `datetime.now(timezone.utc).timestamp()` a second time — a later, larger value. Whether `elapsed > total` ends up strictly true, false, or exactly equal at the boundary depends on how much wall-clock time passed between the two calls, which is unspecified and uncontrolled.

## Fixes

**Fix A — atomic takeover in `_acquire_lock`.** Replace the check-then-replace branch with: read the lock, decide if it's dead/stale (unchanged logic), and if so `os.unlink(lock_path)` (swallowing `FileNotFoundError` — another process may have already taken it over) and then retry the *exact same* `os.open(..., O_CREAT | O_EXCL | O_WRONLY, ...)` call used for the fresh-lock case. The kernel's exclusive-create is what actually arbitrates: whichever racer's post-unlink create call lands first gets `True`; every other racer's create call — whether its own unlink raced or not — hits an existing file and gets `FileExistsError`, so it correctly returns `False` instead of claiming a win it didn't have. No new primitive, reuses the one `_acquire_lock` already has for the fresh case.

**Fix B — deterministic `_is_stale`.** Add an optional `now: datetime | None = None` parameter (defaults to `datetime.now(timezone.utc)`, so the one real call site in `_acquire_lock` is unaffected) and change the comparison from strict `>` to `>=`, matching the test's own stated intent ("exactly at the total timeout (inclusive)"). This removes both the flakiness (test now supplies a single fixed `now`, no second wall-clock read) and the semantic gap (strict `>` never agreed with the "inclusive" test in the first place).

**Fix C — inject `changed_paths` in the four isolation-violating tests.** Each of the four gets `changed_paths=lambda repo_dir, old, new: ["lib/x.py"]` (a non-skippable path, so the carry branch is bypassed exactly as each test already assumes, and no real git subprocess runs against the real repo).

**Fix D — rewrite `test_pid_alive_returns_true_for_permission_error`** to `monkeypatch(os, "kill", raising a PermissionError)` and assert `mh._pid_alive(somepid) is True`; drop the no-op call to the real `os.getpid()` path.

**Fix E — rewrite the force-push half of `test_changed_paths_uses_two_dot_diff`** to actually diverge: after sha2, create an orphan commit (`git checkout --orphan`) as sha3 touching `file3.txt`, then reset back and build sha4 as a normal descendant of sha2 touching `file4.txt`. Two-dot `sha3 sha4` (tree diff) shows `file3.txt` (since sha3's tree has it and sha4's doesn't — pure tree comparison), while three-dot `sha3...sha4` (merge-base diff, base = some common ancestor before sha3's orphan point, or no merge-base at all since orphan) would not include `file3.txt` the same way. Assert `"file3.txt" in paths` to pin two-dot behavior specifically — this is the exact case review named ("diff from the orphaned sha3 to sha4").

## Tests first (and the defect each one proves)

All in `lib/tests/test_main_health.py`; no change to `lib/health_checks.py`, `lib/tests/test_health_checks.py`, `dashboard/*`, or `CONTEXT.md` — already correct and already tested.

1. **Only one winner when two processes race a stale-lock takeover** (new test, proves Fix A) — pre-populate a lock with a dead PID. Monkeypatch `os.unlink` on the lock path to, on its first call, let a *second* `_acquire_lock()` call run to completion first (simulating the interleaving the review described), then proceed. Assert exactly one of the two calls returns `True` and the final lock file's PID is the winner's. (Concretely: monkeypatch `os.open` to recreate the exact race — attempt 1's unlink succeeds, attempt 2's unlink then raises `FileNotFoundError` because attempt 1 already removed it, attempt 2 retries create and hits attempt 1's fresh file, gets `FileExistsError`, returns `False`.) This fails under the current check-then-`os.replace` code (both would return `True`) and passes under Fix A.
2. **Takeover still succeeds in the uncontested case** — existing `test_acquire_lock_takes_over_when_pid_is_dead` and `test_acquire_lock_takes_over_when_stale` stay, re-run against Fix A's new code path (unlink + retry-create instead of replace) to confirm the common case isn't broken.
3. **`test_acquire_lock_atomic_takeover_via_temp_file`** — rename/rewrite: it currently asserts "no `.tmp.*` files left behind," which was true for the temp-file approach; under Fix A there's no temp file at all, so simplify the assertion to just "takeover succeeds and the new PID is written," dropping the now-meaningless `.tmp.*` glob check.
4. **`_is_stale` boundary is deterministic** (fixes Fix B) — rewrite `test_is_stale_includes_worktree_setup_timeout` to build one fixed `now = datetime(...)`, pass `now=now` to every `_is_stale()` call, and assert the boundary (`now_ts - total`) is stale (`>=`), one second before is not, one second after is.
5. **`_pid_alive` actually exercises `PermissionError`** (fixes Fix D) — monkeypatch `os.kill` to raise `PermissionError`, assert `True`.
6. **Two-dot vs three-dot actually diverge** (fixes Fix E) — orphan-branch repo construction as described; assert the two-dot result includes `file3.txt`.
7. **The four isolation-violating tests no longer touch a real repo** (fixes Fix C) — same four tests, each now passes `changed_paths=lambda *_: ["lib/x.py"]`; no behavior change, same assertions, now hermetic. (A `monkeypatch`-based guard — e.g. asserting `subprocess.run` is never called with `"diff"` in its args during these four tests — would over-specify internals; passing a real injected callable is simpler and already the pattern the carry tests use.)
8. **Regression check**: `test_lock_prevents_concurrent_runs`, `test_multiple_refreshes_with_same_commit_only_run_once`, `test_acquire_lock_succeeds_when_none_exists`, `test_acquire_lock_fails_when_held_by_live_pid`, `test_release_lock_only_unlinks_if_pid_matches`, `test_release_lock_handles_corrupted_lock`, and every carry/skip-path test — no logic change needed, re-run after Fixes A/B to confirm nothing regresses.

No new misuse case is needed beyond what the review already surfaced: the ticket's own "How we'll try to break it" (concurrent refreshes, stale/dead-lock takeover, docs-only carry, killed run, temp-HOME isolation) is already covered by the existing test suite (confirmed by reading it in full) — this round's gap was entirely in *how faithfully* those tests exercised the real race, not in missing scenarios.

## Task List

1. `lib/main_health.py`: rewrite `_acquire_lock`'s takeover branch — on `FileExistsError`, decide dead/stale as today, then `os.unlink(lock_path)` (catch `FileNotFoundError`, treat as "someone else already took it") and retry the same `O_CREAT|O_EXCL` create call used for the fresh-lock path; return its result. Delete the temp-file + `os.replace` takeover code entirely.
2. `lib/main_health.py`: add `now: datetime | None = None` to `_is_stale`'s signature (default `datetime.now(timezone.utc)`), and change `>` to `>=` in its comparison.
3. `lib/tests/test_main_health.py`: add the race test for item 1 above (two interleaved `_acquire_lock()` calls against one stale lock, exactly one wins).
4. `lib/tests/test_main_health.py`: simplify `test_acquire_lock_atomic_takeover_via_temp_file` to drop the now-obsolete `.tmp.*` assertion; keep the PID-replaced assertion.
5. `lib/tests/test_main_health.py`: rewrite `test_is_stale_includes_worktree_setup_timeout` to inject a fixed `now` into all three `_is_stale()` calls.
6. `lib/tests/test_main_health.py`: rewrite `test_pid_alive_returns_true_for_permission_error` to monkeypatch `os.kill` raising `PermissionError`.
7. `lib/tests/test_main_health.py`: rewrite `test_changed_paths_uses_two_dot_diff`'s second scenario to use an orphan commit, so two-dot and three-dot diffs provably differ; assert on that difference.
8. `lib/tests/test_main_health.py`: add `changed_paths=lambda *_: ["lib/x.py"]` to `test_lock_survives_killed_run`, `test_run_suite_exception_returns_prior`, `test_run_suite_exception_releases_lock`, and `test_cannot_acquire_lock_returns_prior`.
9. Run `lib/tests/test_main_health.py` in full (not just the new/changed tests), plus `lib/tests/test_health_checks.py` and `dashboard/test/boot_data.test.js`, to confirm no regression and clean collection before opening the PR.
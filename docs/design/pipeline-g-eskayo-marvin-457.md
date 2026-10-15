## North-star fit

Reuses everything the prior attempt already reused — still the same single call site (`ticket_pipeline._refresh_main_health()` → `main_health.py refresh`, unaffected), still inside the same two helpers (`_acquire_lock`/`_release_lock`) plus the carry branch in `refresh()`, still `fcntl` (already imported, already POSIX-only via `os.kill`). No new file, no new dependency. The only correction to the prior doc's own stated fit: it called the review's notes "theoretical" in one place and treated the doc-carve-out as already closed; re-reading the real repo this round turned up a concrete miss the prior pass didn't check for — `CONTEXT.md` is read for real content by `test_marvin_launcher.py::test_every_glossary_launch_kind_is_declared_and_nothing_else`, and the already-landed `TEST_RELEVANT_DOCS` allowlist didn't include it, so it would have been a second live instance of the exact 2026-10-07 bug this ticket exists to prevent. Simplest sufficient fix for all four must-fix findings: tighten the existing match logic and add a PID check to an existing release path, not a new coordination mechanism or a directory-prefix allowlist (checked and rejected below — it's less safe for this repo, not more). Token cost: unchanged from the prior attempt — microseconds per refresh, still saving the 5.5-minute pytest runs this ticket exists to stop duplicating. Leaves Gil more capable: a red main now always re-verifies instead of being able to wedge behind a docs commit, and a slow `git worktree remove` can no longer let two processes silently stomp each other's lock.

## What the review found, re-verified against the current worktree (not re-derived from the prior doc)

**1. A red verdict can still be carried.** `lib/main_health.py:180` gates the carry branch on `prior.get("ok") is not None` — `False` is not `None`, so a failing prior carries forward past any docs-only commit just as readily as a passing one. Confirmed live: `main_health.py` deliberately runs tests that read other repos' data (its own docstring says so), so a red can be a flake or depend on data outside the diff; this gate currently lets that red survive indefinitely behind a stream of docs/log/auto-sync commits, exactly as the review describes.

**2/3. The already-landed `TEST_IRRELEVANT`/`TEST_RELEVANT_DOCS` fix is still unsafe, and I found a live instance, not just a theoretical one.**
`TEST_IRRELEVANT` (`lib/main_health.py:47-53`) still has `"docs/*"` as its own pattern, separate from `"*.md"`. `fnmatch` has no path-separator awareness — `*` becomes regex `.*`, which crosses `/`. I confirmed `docs/*` therefore matches a real, non-markdown, non-doc file that exists in this repo today: **`docs/diagrams/make_pipeline_diagrams.py`**. That file is itself scanned by `lib/tests/test_marvin_launcher.py::test_no_model_run_starts_outside_the_launcher` (its `_sources()` walks every `.py`/`.sh` file in the repo, excluding only `tests/test/node_modules/venv/.venv/graphify-out`). A change to that file that introduces a raw subprocess call — exactly what that test exists to catch — would currently be silently carried past as "docs-only."
Separately, `TEST_RELEVANT_DOCS` (`lib/main_health.py:39-43`) lists three files real tests assert content about, but is missing a fourth I found by re-reading `lib/tests/test_marvin_launcher.py:45`: `test_every_glossary_launch_kind_is_declared_and_nothing_else` reads the real repo `CONTEXT.md` and asserts the launch-kind glossary is present in it. `CONTEXT.md` matches `*.md` and isn't in the exception list, so a `CONTEXT.md`-only commit (this very ticket's own diff touches `CONTEXT.md`) would be wrongly carried.
I checked the review's third-listed risk — a future `lib/tests/*.md` fixture — and confirmed none exists yet (`Glob lib/tests/**/*.md` → none), but per the review's own "at least" framing I'm closing it pre-emptively since it's a one-line, zero-cost prefix exclusion.
I deliberately did **not** adopt the review's first suggested alternative ("match by allowlist of relevant prefixes like `lib/`") — re-reading the repo root shows source and test-relevant content living under `lib/`, `dashboard/`, `bin/`, `config/`, `skills/*/SKILL.md`, and even `docs/diagrams/*.py`; an allowlist would have to enumerate all of these and would go stale the next time a script lands in a new top-level directory. A short denylist of doc/log *shapes* (`*.md`, `*.log`, `bench/metrics/*`, `sync-log.md`) plus a handful of named exceptions is the smaller, more stable surface, and is what the ticket itself specified.

**4/5/6/7. `test_lock_single_flight_blocks_concurrent_refresh` (`lib/tests/test_main_health.py:58-94`) and the production gap it was supposed to be testing for.** The test starts `t1` and `t2`, discards `t2`'s result, then starts a third thread `get_res2` and asserts on *that* — so it's unclear which of `t2`/`get_res2` is under test, and it depends on `sleep(0.1)`/`sleep(0.05)` for ordering, which can flake under load. Chasing why the test needed two attempts at a second thread led to the real defect: `_release_lock` (`lib/main_health.py:116-121`) unlinks the lock file unconditionally, with no check that the lock still names *our* PID. `LOCK_STALE_SECONDS` (2100s) is sized against fetch(60s) + `worktree add`(120s) + suite(1800s) = 1980s, but `_run_suite`'s `finally` (`lib/main_health.py:157`) calls `git worktree remove --force` with **no timeout at all** — so the real worst case is unbounded. If a run's cleanup step hangs past `LOCK_STALE_SECONDS`, a second process correctly takes the lock over as stale; when the first process's hung cleanup eventually finishes and reaches `_release_lock`, it deletes the *second* process's live lock, defeating single-flight for both.

## Fix design

**Fix 1 — never carry a failing verdict (`lib/main_health.py:180`):**
```python
# A red is never carried, even past test-irrelevant changes: main_health deliberately runs tests
# that read other repos' data, so a failure can be a flake or depend on something outside this
# diff. Only a real rerun can clear it (marvin#457 review).
if prior.get("ok") is True:
```

**Fix 2 — tighten the doc/log match (`lib/main_health.py:36-64`):**
```python
# Doc files real tests in lib/tests read from disk and assert content about (marvin#457 review):
# never carry past a change to these even though they match TEST_IRRELEVANT below. A future test
# that starts reading a new doc file must add it here too.
TEST_RELEVANT_DOCS = (
    "docs/north-stars.md",  # test_north_stars.py asserts its exact text
    "docs/impact.md",       # test_impact_showcase.py asserts headings + evidence links
    "CONTEXT.md",           # test_marvin_launcher.py asserts the launch-kind glossary is present
    "README.md",            # test_impact_showcase.py asserts a docs/impact.md link inside it
)

# Patterns for changes that do not affect pytest results (fnmatch; "*" crosses "/", so these are
# kept to doc/log *shapes* only -- no bare "docs/*", which would also match non-doc files that
# live under docs/, e.g. docs/diagrams/make_pipeline_diagrams.py, itself scanned by a real test.
TEST_IRRELEVANT = (
    "bench/metrics/*",
    "*.md",
    "*.log",
    "sync-log.md",
)


def _is_test_irrelevant(path: str) -> bool:
    if path in TEST_RELEVANT_DOCS or path.startswith("lib/tests/"):
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in TEST_IRRELEVANT)
```

**Fix 3 — `_release_lock` only removes a lock it still owns, and bound `worktree remove` (`lib/main_health.py:116-157`):**
```python
WORKTREE_REMOVE_TIMEOUT_S = 60
LOCK_STALE_SECONDS = SUITE_TIMEOUT_S + 600  # fetch 60 + add 120 + suite 1800 + remove 60 = 2040; margin 360s


def _release_lock(lock_path: Path) -> None:
    """Release the lock -- but only if it's still ours. A slow `git worktree remove` could let
    LOCK_STALE_SECONDS elapse before we get here; another process may have already taken the lock
    over as stale. Unlinking unconditionally would then delete ITS lock (marvin#457 review)."""
    meta_path = lock_path.with_name(lock_path.name + ".meta")
    try:
        meta_fd = os.open(str(meta_path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return
    try:
        fcntl.flock(meta_fd, fcntl.LOCK_EX)
        try:
            data = json.loads(lock_path.read_text())
        except (OSError, ValueError):
            return
        if data.get("pid") != os.getpid():
            return
        try:
            lock_path.unlink()
        except OSError:
            pass
    finally:
        fcntl.flock(meta_fd, fcntl.LOCK_UN)
        os.close(meta_fd)


def _run_suite(run=subprocess.run) -> tuple[bool, list[str], str]:
    tmp = tempfile.mkdtemp(prefix="main-health-")
    try:
        run(["git", "worktree", "add", "-q", "--detach", tmp, "origin/main"], cwd=REPO_DIR, check=True, capture_output=True, timeout=120)
        p = run([str(VENV_PY), "-m", "pytest", "lib/tests", "-q", "-p", "no:cacheprovider"], cwd=tmp,
                capture_output=True, text=True, timeout=SUITE_TIMEOUT_S)
        last = [l for l in p.stdout.strip().splitlines() if l.strip()][-1:] or [""]
        return p.returncode == 0, failed_ids(p.stdout), last[0].strip(" =")
    finally:
        run(["git", "worktree", "remove", "--force", tmp], cwd=REPO_DIR, capture_output=True, timeout=WORKTREE_REMOVE_TIMEOUT_S)
```
`_release_lock` reuses the same `.meta` flock `_acquire_lock` already holds for its own critical section, so acquire and release fully serialize against each other — this closes the race, not just narrows it. `_run_suite` gains an injectable `run` (matching this codebase's existing DI style, e.g. `check_ticket_failure_streaks(run=subprocess.run)`) purely so the new timeout is independently testable; its default behavior for the real caller is unchanged.

**Test-quality fix (flagged by review as a problem with the test, not production code) — rewrite `test_lock_single_flight_blocks_concurrent_refresh`** using `threading.Event`s instead of `sleep()`, with exactly one background thread and one synchronous foreground call, so it's unambiguous which call is under test and it can't flake under load (shown under Tests below).

**Minor, same-touch test-quality fix** (in review's *notes*, not its *must-fix* list, but one line and already in a file I'm editing): `test_lock_with_other_users_pid_is_treated_as_alive` asserts the same outcome on both the root and non-root branch, so under root it never exercises the `PermissionError` path its docstring claims to test. Add `@pytest.mark.skipif(os.getuid() == 0, reason=...)` and drop the dead branch. `import pytest` is not currently in `test_main_health.py` — add it.

No changes needed to `lib/health_checks.py`, `dashboard/electron/main/boot_data.js`, or their tests — re-read all four (already modified in this worktree from the prior attempt). `check_main_health`'s shape (`sha`/`ok`/`failed`/`summary`/`checked_at`/`carried`/`carried_from`) is untouched by the fixes above, and I verified the review's *note* about `carried_from` overflowing the boot line is specifically about a 40-char sha — in production, `carried_from` is always what `_head()` returns (`git rev-parse --short origin/main`, ~7-8 chars), so it's a test-data choice, not a live bug; leaving it alone, as the prior doc concluded.

## Decisions

None. Every change above is a bug fix with one correct answer (never carry a known failure; don't let a loose glob match a real test-input file; don't delete a lock you no longer own) or a verified factual gap (two concrete files — `docs/diagrams/make_pipeline_diagrams.py` and `CONTEXT.md` — proven by reading the repo, not assumed), not a product/UX choice for Gil to pick between.

## Tests to write first

**Kept unchanged** (already correct, already pass, already cover concurrency via threads/barrier, a dead PID via a real spawned-and-waited subprocess, a too-old live PID, corrupted JSON, mixed relevant/irrelevant paths, unreadable diff fails closed, empty diff vacuously carries, first-run never carries, a killed `run_suite` leaves state untouched, sequential calls don't leak, missing parent dir is created, malformed `started_at`, bump of `checked_at` on carry): `test_a_green_run_is_recorded_with_the_commit_it_checked`, `test_an_unchanged_commit_is_not_rechecked`, `test_a_new_commit_is_checked_and_a_failure_names_the_tests`, `test_a_run_that_could_not_happen_keeps_the_last_good_answer`, `test_pytest_failures_are_read_from_the_output`, `test_live_lock_file_is_respected`, `test_stale_lock_with_dead_pid_is_taken_over`, `test_stale_lock_with_old_timestamp_is_taken_over`, `test_corrupted_lock_file_is_taken_over`, `test_docs_only_commit_carries_prior_verdict`, `test_chained_docs_carry_points_to_original_tested_sha`, `test_mixed_relevant_and_irrelevant_changes_runs_suite`, `test_unreadable_diff_runs_suite_fails_closed`, `test_empty_diff_vacuously_carries`, `test_first_run_never_carries`, `test_killed_run_leaves_state_unchanged_and_releases_lock`, `test_sequential_calls_do_not_leak_lock`, `test_lock_parent_directory_is_created`, `test_concurrent_stale_takeover_has_exactly_one_winner`, `test_malformed_started_at_is_treated_as_stale`, `test_carry_bumps_checked_at_so_health_does_not_go_stale`, `test_pattern_matching_for_test_irrelevant_paths`; `check_main_health`/`boot_data.js` tests unchanged.

**Rewritten (the review found the test itself flawed, not just the code):**
1. `test_lock_single_flight_blocks_concurrent_refresh` — replace the `sleep()`-ordered, three-thread version with:
```python
def test_lock_single_flight_blocks_concurrent_refresh(tmp_path):
    state, lock = tmp_path / "m.json", tmp_path / "lock.json"
    suite_started, release_suite, calls = threading.Event(), threading.Event(), []

    def blocking_suite():
        calls.append("start")
        suite_started.set()
        release_suite.wait(timeout=5)
        return (True, [], "ok")

    t1 = threading.Thread(target=lambda: mh.refresh(state_path=state, lock_path=lock, head=lambda: "sha1",
                                                      run_suite=blocking_suite, now=NOW))
    t1.start()
    assert suite_started.wait(timeout=5), "first refresh never started the suite"

    res2 = mh.refresh(state_path=state, lock_path=lock, head=lambda: "sha1",
                       run_suite=lambda: calls.append("second") or (True, [], "ok"), now=NOW)

    release_suite.set()
    t1.join(timeout=5)
    assert calls == ["start"], f"run_suite should only run once, got {calls}"
    assert res2.get("skipped") == "already running"
```
2. `test_lock_with_other_users_pid_is_treated_as_alive` — `@pytest.mark.skipif(os.getuid() == 0, reason="root can signal pid 1 directly, which skips the PermissionError branch this test targets")`, single assertion `mh._lock_is_stale(lock, now=NOW) is False`. Add `import pytest`.
3. `test_doc_files_read_by_real_tests_are_not_treated_as_irrelevant` — add `assert mh._is_test_irrelevant("CONTEXT.md") is False` and `assert mh._is_test_irrelevant("lib/tests/fixture.md") is False`.

**New (one per must-fix finding, each fails on the pre-fix code):**
4. `test_a_red_main_reruns_even_on_a_docs_only_commit` — prior `ok: False`; `changed_paths` returns only `["docs/file.md"]`; assert `run_suite` is called (`len(calls) == 1`), `res["ran"] is True`, `"carried" not in res`. Fails under `prior.get("ok") is not None`.
5. `test_a_non_doc_file_under_docs_is_not_treated_as_irrelevant` — `assert mh._is_test_irrelevant("docs/diagrams/make_pipeline_diagrams.py") is False`, tied to the real file in this repo. Fails while `"docs/*"` is in `TEST_IRRELEVANT`.
6. `test_release_lock_removes_its_own_lock` — write a lock with `os.getpid()`; call `mh._release_lock`; assert it's gone.
7. `test_release_lock_does_not_remove_another_owners_lock` — spawn `subprocess.Popen(["sleep", "5"])`, write a lock naming its PID, call `mh._release_lock`, assert the lock file still exists and still names that PID; terminate the subprocess in a `finally`. Fails under the current unconditional `unlink()`.
8. `test_run_suite_bounds_worktree_remove_with_a_timeout` — a fake `run(cmd, **kw)` that records every call and returns a passing `CompletedProcess` for `worktree add` and the pytest invocation; call `mh._run_suite(run=fake_run)`; assert the `["git", "worktree", "remove", ...]` call's kwargs include a `timeout`. Fails on the current untimed call.

All new/rewritten tests use only `tmp_path`-scoped `state_path`/`lock_path`/fake subprocesses, never `~/.claude`/`~/.agents`, matching the acceptance criterion and the existing file's pattern.

## Task List

1. `lib/main_health.py`: change the carry gate at line 180 from `prior.get("ok") is not None` to `prior.get("ok") is True`, with the comment explaining why a red never carries.
2. `lib/main_health.py`: add `"CONTEXT.md"` to `TEST_RELEVANT_DOCS`; remove `"docs/*"` from `TEST_IRRELEVANT`; add the `path.startswith("lib/tests/")` exclusion to `_is_test_irrelevant`.
3. `lib/main_health.py`: rewrite `_release_lock` to guard the read-check-unlink with the existing `.meta` flock and only unlink when the lock's `pid` is `os.getpid()`.
4. `lib/main_health.py`: add `run=subprocess.run` parameter to `_run_suite`, route all three subprocess calls through it, add `WORKTREE_REMOVE_TIMEOUT_S = 60` and pass it as the `worktree remove` call's timeout; bump `LOCK_STALE_SECONDS` to `SUITE_TIMEOUT_S + 600`.
5. `lib/tests/test_main_health.py`: add `import pytest`; rewrite `test_lock_single_flight_blocks_concurrent_refresh` (Event-based); fix `test_lock_with_other_users_pid_is_treated_as_alive` (skipif + single assertion); extend `test_doc_files_read_by_real_tests_are_not_treated_as_irrelevant`; add the four new tests (4–8 above, minus the duplicate numbering: red-carry, docs-non-md, release-owns-its-lock, release-skips-others-lock, worktree-remove-timeout).
6. Run `pytest lib/tests/test_main_health.py -q` to green, then the full `lib/tests` suite once to confirm no collateral breakage.
7. Re-read `lib/health_checks.py`, `dashboard/electron/main/boot_data.js`, and their tests once more after the above lands, to reconfirm the carried-marker display still matches the (unchanged) `checked_at`/`carried_from` shape — no edits expected, just a confirmation pass before opening the PR.
## North-star fit

**Reuses before adding anything new:** this pass touches nothing beyond the one module and its tests that code review flagged. `scanner_role.is_primary`, `PRIMARY_PREFIX`, `task_dispatch.SSH_OPTS`, `machine_profile.remote_devices()`/`registry_id()`, and the `(claude call failed:` / `_Quarantined by safety-monitor` literal markers are all unchanged, correct, and confirmed still in place by re-reading `lib/brief_fallback.py`, `skills/improve/scripts/daily_digest.py`, `skills/research-colony/scripts/research_digest.py`, `skills/research-colony/scripts/run_colony.py`, and `lib/morning_brief.py` directly (not from the prior design doc's description of them). I independently confirmed: the `usual_hour`/`usual_minute`/`grace_minutes` per-call-site parameters already exist and are passed by all three call sites (08:30/09:00/09:15), `past_deadline()` already converts via `now.astimezone()`, `produced()`'s placeholder/quarantine checks are already substring (`in`) not `startswith`, `build_lock()` is already gone from both the module and its tests, and `morning_brief.py` already has a top-level `build()` function. **None of that is re-touched.** What's actually still broken, confirmed by reading the live code rather than trusting the previous design doc's claim that it was fixed:

1. `_infer_remote_path()` (`lib/brief_fallback.py:36-38`) still hardcodes `f"$HOME/.claude/{local_path.name}"` — drops the `daily-digest/`/`research-digest/`/`briefs/` subdirectory every real caller needs.
2. `read_remote()` (`lib/brief_fallback.py:62`) does `shlex.quote(remote_path)` on the *whole* string including the literal `$HOME` — single quotes block all shell expansion, so the remote `cat` is handed a literal `$HOME/...` path that doesn't exist on the remote shell, and every SSH read fails.
3. `test_unreadable_local_file_falls_through_to_remote` (`lib/tests/test_brief_fallback.py:156-188`) calls `now=datetime(2026,10,22,10,0,0,tzinfo=timezone.utc)` through `should_run()`, which (with the now-correct `past_deadline`) returns "before deadline" in most US timezones before ever reaching the `produced()`/remote-fallthrough code the test claims to exercise. The `chmod(0o000)`/`chmod(0o644)` pair isn't wrapped in `try/finally`, and there's no skip for root (which ignores file permissions), so the test can pass without testing anything, or fail to restore permissions on an assertion failure.

**Simplest sufficient approach:** three local, surgical fixes plus the tests that would have caught each — no redesign, no new module, no touching code that's already correct.
- `_infer_remote_path()` becomes home-relative: `local_path.relative_to(Path.home())`, falling back to just the filename when the path isn't under `~` (keeps today's degenerate behavior for anything genuinely outside `~/.claude`, which is the only case the old hardcoded form accidentally got right).
- `read_remote()` splits the `$HOME/` prefix from the rest of the path: emit the literal, unquoted `"$HOME/"` so the remote shell expands it, immediately followed (no space, so bash concatenates the two into one word) by `shlex.quote()` of the home-relative remainder — so `$HOME` still expands and the attacker-reachable part (whatever `local_path.name` turns out to be) is still fully shell-quoted. Paths that don't start with `$HOME/` keep the existing full-string `shlex.quote()`.
- The test is rewritten to call `produced()` directly instead of `should_run()`, which removes the deadline/timezone coupling entirely rather than patching around it — it only needs to prove the local→remote fallthrough, not re-prove `should_run`'s deadline math (already covered by `TestPastDeadline`). `chmod` restore moves into `finally`, and a `pytest.skip` guards the root case.

**Where this saves/spends tokens:** zero new daily cost — this is the fix that makes the already-paid-for fallback mechanism actually work. Today, with both bugs live, every SSH read to the Mini fails, so a standby's `produced()` check always falls through to `False` and it silently rebuilds regardless of whether the Mini already produced the output — which is exactly the duplicate-model-call problem ADR 0067 exists to kill. Fixing this is what turns the already-built mechanism into a real saving.

**More capable or more passive:** more capable — without this fix the "fallback" silently never actually checks the primary over SSH (it falls through to "not produced" every time on a read failure, by design — fails open, which is correct for an unreachable primary but wrong when the real bug is a malformed command), so the standby would quietly duplicate work it believes it verified was necessary. Fixing it makes the automation trustworthy enough to leave alone, which is the whole point of consolidating onto the Mini.

**ADR/CONTEXT check:** `CONTEXT.md`'s "Brief owner" bullet (`CONTEXT.md:1442`, revised 2026-10-22) is accurate about the three schedule times and the fallback mechanism, but its closing clause — "removes the duplicate work (ADR 0067) **and the cross-machine-merge LLM digest call (see note below)**" — overstates what's shipped: there is no "note below" anywhere near it (a dangling reference), and `cross_machine_merge.py`'s merge step is still wired on both machines in `lib/health_checks.py`/`lib/cron_health.py`, unchanged, pending the still-open `retire-cross-machine-merge` Decision below. This is a real doc/code mismatch a reader would trust; I'm correcting that one sentence as part of this pass since it's free and directly touches the subsystem this ticket owns. I'm **not** touching the separate, older "Fan-out + merge (mode 2)" section (`CONTEXT.md:189-218`), which records a 2026-07-08 decision that research-colony running on both machines is "redundant by design, not a bug" for result diversity — that decision is now superseded in practice by the 2026-10-22 "Brief owner" revision and the code already implements the new behavior, but reconciling that older section's text is a documentation-cleanup task in its own right, not a defect in this ticket's code; flagging it here rather than scope-creeping into a rewrite.

---

## Decisions

Carried over unchanged from the prior attempt — still genuinely unresolved, still not required to resolve the 3 must-fix defects below, so not blocking this pass:

<!-- marvin:decisions -->
### quarantine-counts-as-produced: Does a quarantined (but not failed) digest count as "the Mini produced it"?
The code today implements option A (a guess, never confirmed). Please confirm or override.
- [ ] A: Quarantined counts as produced — the Mini did its job; a held-back item is a safety-check outcome, not an outage. The laptop never rebuilds just because content got quarantined.
- [ ] B: Quarantined counts as not produced — if the brief chain got nothing usable, the laptop should still try, in case its own run clears the safety check.

### retire-cross-machine-merge: Remove `cross_machine_merge.py`'s LLM digest/research-digest merge step now, or leave it in place?
Still untouched in this worktree.
- [ ] A: Remove `run_merge_authority` and its daily-digest/research-digest loop now — ADR 0067 says this step "becomes unnecessary for these jobs," and leaving it risks a stray LLM merge call + a third `{day}-merged.md` write-back on the rare day the fallback actually fires.
- [ ] B: Leave it in place for now (it already runs zero LLM calls on a normal day, since one side's file won't exist) and remove it in a separate follow-up ticket.

---

## Tests to write first

All against the real collaborator pattern already used in this suite: `monkeypatch`/`tmp_path` for the filesystem, an injected `run=` stub for SSH, and — new in this pass, for the injection-safety test — a real local `sh -c` to verify actual shell-expansion semantics rather than trusting string equality (the mock can't tell us whether the command would actually behave correctly in a shell, which is precisely how bug #2 escaped the last two reviews).

**For defect #1 (`_infer_remote_path`):**
1. `test_infer_remote_path_preserves_subdirectory` — parametrized over the three real conventions: `Path.home()/".claude"/"daily-digest"/"2026-10-22.md"` → `"$HOME/.claude/daily-digest/2026-10-22.md"`, and the same for `"research-digest"` and `"briefs"`. Fails today (produces `"$HOME/.claude/2026-10-22.md"`, dropping the subdirectory).
2. `test_infer_remote_path_falls_back_to_filename_outside_home` — a `tmp_path` path (not under `Path.home()`) → `f"$HOME/{name}"`. Replaces the two existing tests (`test_infer_remote_path_from_local`, `test_infer_remote_path_preserves_filename`) that hard-coded the buggy `tmp_path → "$HOME/.claude/..."` assumption and would otherwise keep passing against the fix.

**For defect #2 (`read_remote` quoting):**
3. `test_read_remote_lets_home_expand_but_quotes_rest` — capture the command `read_remote()` builds via a `run=` stub, then actually execute it through `sh -c` locally (not ssh) with `$HOME` set in the test's own environment, and assert the echoed path matches the real expanded home-relative path. This is the regression test for the exact bug: today's code wraps the literal `$HOME` in single quotes, so this assertion fails (the shell prints the literal string `$HOME/...` instead of the expanded path).
4. `test_read_remote_quotes_against_shell_injection` — adversarial/misuse case: build a remote path whose home-relative component contains shell metacharacters (e.g. `` ; touch marker `` or a backtick command substitution), run the constructed command through a real local `sh -c`, and assert the injected side effect (a marker file) never happens. This is the test that would catch a naive "fix" that drops quoting entirely to make `$HOME` expand (trading one bug for a worse one) — exactly the kind of adversarial check the guiding principles require for anything that builds a shell command string.

**For defect #3 (the test itself):**
5. Rewrite `test_unreadable_local_file_falls_through_to_remote` to call `brief_fallback.produced()` directly (not `should_run()`), removing all dependence on wall-clock/timezone: `chmod(0o000)` the local file, assert `produced(local_path, remote_path=..., host=..., run=run_mock)` is `True` via the remote stub, with the `chmod(0o644)` restore in `finally` and a `pytest.skip(...)` when `os.getuid() == 0`. This directly tests the fallthrough the old test only accidentally exercised (or didn't).

**CONTEXT.md:** no test — it's a one-sentence doc correction, not code.

**Misuse/break-test coverage already satisfied, confirmed by reading (no new test needed):** per-call-site deadline parameterization (`TestParameterization`), clock-skew/local-clock-only comparison (`test_clock_skew_never_compares_across_machines`), empty/whitespace/placeholder/quarantine content (`TestProduced`), registry-lookup failure (`test_registry_lookup_failure_treated_as_not_produced`), repeated same-day calls (`test_same_day_idempotent_across_repeated_calls`), two-call Mini-down sequence (`test_mini_down_all_morning_laptop_builds_once`).

---

## Task List

1. In `lib/brief_fallback.py`: fix `_infer_remote_path()` to compute the path relative to `Path.home()` (falling back to just the filename when the path isn't under `~`), instead of hardcoding `.claude/{name}` (defect #1).
2. In `lib/brief_fallback.py::read_remote()`: split any `remote_path` starting with `$HOME/` into the literal unquoted `"$HOME/"` plus `shlex.quote()` of the remainder, concatenated with no space so the remote shell expands `$HOME` and safely quotes the rest; keep full `shlex.quote()` for any remote_path that doesn't start with `$HOME/` (defect #2).
3. In `lib/tests/test_brief_fallback.py`: replace `test_infer_remote_path_from_local`/`test_infer_remote_path_preserves_filename` with `test_infer_remote_path_preserves_subdirectory` (parametrized: daily-digest/research-digest/briefs) and `test_infer_remote_path_falls_back_to_filename_outside_home` (tests 1–2 above).
4. In `lib/tests/test_brief_fallback.py`: add `test_read_remote_lets_home_expand_but_quotes_rest` and `test_read_remote_quotes_against_shell_injection`, both executing the constructed command through a real local `sh -c` (tests 3–4 above).
5. In `lib/tests/test_brief_fallback.py`: rewrite `test_unreadable_local_file_falls_through_to_remote` to call `produced()` directly, with `try/finally` chmod restore and a root skip (test 5 above).
6. In `CONTEXT.md:1442`: correct the "Brief owner" bullet's closing clause to stop claiming the cross-machine-merge LLM call is already removed; state plainly that retiring it is the still-open `retire-cross-machine-merge` Decision, and that it's currently wired but already runs zero LLM calls on a normal day.
7. Run `lib/tests/test_brief_fallback.py` (and the full `lib/tests/`, `skills/improve/scripts/tests/`, `skills/research-colony/scripts/tests/` suites) and confirm: each of the 5 new/rewritten tests fails against the current, unfixed code and passes once steps 1–2 land — i.e. verify each test actually exercises the bug it claims to catch, not just that the suite goes green.
8. In the PR description: note that `cross_machine_merge.py` is untouched pending the `retire-cross-machine-merge` Decision, and that the laptop/Mini install-location swap for the `daily-digest`/`research-colony`/`morning-brief` plists is a manual `launchctl` step this PR's diff cannot perform — both carried forward from the prior attempt, still true, still outside this PR's diff.
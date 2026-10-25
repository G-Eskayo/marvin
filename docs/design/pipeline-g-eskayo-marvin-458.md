## North-star fit

**Reuses before adding anything new:**
- `lib/scanner_role.py:27-28` (`is_primary()`) and `lib/machine_profile.py:175-196` (`registry_id()`, `remote_devices()`) — the same primary/standby primitives the ticket-scanner fallback already uses. `lib/brief_fallback.py` (already sitting, uncommitted, in this worktree) is built on top of them, same shape as `should_scan()` (`lib/scanner_role.py:76-82`).
- `lib/tests/conftest.py`'s `_isolate_*`/`_no_real_*` autouse-fixture convention (e.g. `_isolate_board_registry`, `_no_real_github`) — this is the established pattern for "a test must never touch real `~/.claude` state or a real network call," and it is the piece the previous attempt skipped. I'm reusing it, not inventing a new isolation mechanism.

**I did not take the ticket/prior design doc's claims on faith — I read the actual code.** This worktree already holds the previous attempt's full uncommitted diff (`git status` shows it dirty, branch up to date with `origin/main`). I read every touched file directly rather than trusting the prior design doc's description of PR #600, and found the **real, code-verified cause of the regression**, which the prior design doc missed entirely:

1. **`skills/improve/scripts/daily_digest.py:335`** — `OUT_FILE.write_text(marker + header + ...)` references a `marker` variable that is **never defined anywhere in the file**. This is a `NameError` on every run that reaches the write step — i.e. almost every "happy path" test of `daily_digest.main()`. Confirmed by `grep -n marker`.
2. **The gate replaced the old short-circuit instead of composing with it.** `daily_digest.main()` and `research_digest.generate()`'s *first* check used to be `if OUT_FILE.exists(): return`. The diff replaced it with `decision = brief_fallback.should_run(...)`, but `should_run()` returns `Decision(True, "primary")` for the primary machine **unconditionally**, with no reference to whether today's output already exists. On the primary (which is what this very pipeline runs on — PR #600's own body says `Device: mac-mini-1`), every invocation now falls through into full content generation even when today's digest is already sitting on disk, only to discard the result at a *second*, late "pre-write recheck." That's wasted model calls on the machine this ticket is trying to stop double-calling, and it's exactly what breaks the pre-existing `skills/improve/scripts/tests/test_daily_digest.py::test_main_short_circuits_when_out_file_exists` (line 287), which asserts `call_claude`/`roadmap_summary`/etc. are never called when `OUT_FILE` exists — I read that test; it isn't patched for `brief_fallback` at all, so it now hits the regenerate path and fails its own `AssertionError` sentinels.
3. **No test isolation exists for the new `machine_profile`/SSH surface.** `lib/tests/conftest.py` isolates every other piece of real `~/.claude` state (`board_registry`, `job_events`, `error_log`, a fake `gh`, a fake `du`...) but has nothing for `machine_profile.registry_id()` (which reads the real `~/.claude/marvin-network.json`/`machine-profile.json`) or for `brief_fallback.read_remote()`'s real `subprocess.run(["ssh", ...], timeout=15)` default. `skills/improve/scripts/tests/` and `skills/research-colony/scripts/tests/` have **no `conftest.py` at all**. Three previously I/O-light, fully-mocked test suites (`test_daily_digest.py`, the new `test_run_colony.py`, and any future `research_digest` tests) now transitively reach this unmocked path through `main()`/`generate()`. On any machine where `registry_id()` doesn't resolve to a `mac-mini*` id, any test invoking these entry points past the usual-hour deadline falls into a real 15-second-timeout SSH attempt against a real Tailscale hostname — this is the kind of time-budget-exhaustion pattern that would cut off a later-running vitest phase mid-suite, which matches the reported shape of the regression (`vitest_passed` collapsing 2164→118 while `vitest_failed` barely moved) far better than any hypothesis in the prior design doc, which never looked at this.

Everything **else** already in this worktree's uncommitted diff is correct and reusable as-is, verified by reading it directly rather than assuming: `CONTEXT.md`'s "Brief owner" bullet (already matches ADR 0067's schedule pairs and the open `retire-cross-machine-merge` question — no further edit needed), `lib/cron_health.py`'s new `morning-brief` entry, `lib/health_checks.py`'s `JOB_PLACEMENT` remap and `check_brief_builder()` (which only touches `morning_brief.builder_of()` and the pure `brief_fallback.past_deadline()` — zero I/O, no isolation risk), all four plist files (the `WorkingDirectory` typo fix is correct and in scope since this ticket already edits that file), and `lib/brief_fallback.py` plus its test file (every test there already injects `run=` explicitly — I checked all 40+ call sites — this file is not implicated in the regression).

**Simplest sufficient approach:** fix the three defects above in place rather than regenerating ~1,400 lines from scratch. This is strictly less work than either of the prior attempts' strategies (hand-authoring everything fresh, or a wholesale `git show 8f7eae31` materialize-and-hope) and is grounded in a line-by-line read of what's actually broken, not a guess.

**Where this saves/spends tokens:** fixing three small, precisely-located defects is far cheaper than another full-suite regression cycle (this is the "halve the model calls" ticket — ADR 0067 — and the defect itself was causing the *opposite*, wasted regeneration on the primary). The isolation-fixture fix also prevents the specific failure mode (test-time SSH hangs) that is the most parsimonious explanation for burning the whole suite's time budget.

**More capable, not just passive:** Health gains a real "which machine built today's brief, or did neither" signal (AC4), and the duplicate-run/sync-conflict problem ADR 0067 names stops, once this lands and the manual `launchctl` placement swap (below) is done.

**One real design risk, already handled correctly in this worktree:** the brief stays at 09:45 primary / 10:45 fallback (not moved earlier) — correct, since write() is idempotent and a too-early primary slot risks building before the research digest lands.

**Known, out-of-scope limitation (flagged, not fixed):** the physical machine swap — making the Mini actually run the primary-timed plist and the MacBook the fallback-timed one — is a manual `launchctl bootstrap`/`bootout` step on each physical machine. No diff in this repo can perform it. The PR must say so plainly, and it must be surfaced to Gil directly, not left only in the PR body, since it's a step he has to finish by hand before AC1 is actually true on the ground.

---

## Decisions

Neither has an owner answer anywhere in the ticket's 99 comments or PR #600's history:

```markdown
## Decisions
<!-- marvin:decisions -->
### quarantine-counts-as-produced: Does a quarantined (but not failed) digest count as "the Mini produced it"?
- [ ] A: Quarantined counts as produced — the Mini did its job; a held-back item is a safety-check outcome, not an outage. The laptop never rebuilds just because content got quarantined. (implemented below)
- [ ] B: Quarantined counts as not produced — if the brief chain got nothing usable, the laptop should still try, in case its own run clears the safety check.

### retire-cross-machine-merge: Remove `cross_machine_merge.py`'s LLM digest/research-digest merge step now, or leave it in place?
- [ ] A: Remove `run_merge_authority` and its daily-digest/research-digest loop now — ADR 0067 says this becomes unnecessary for these jobs, and leaving it risks a stray LLM merge call on the rare day the fallback fires.
- [ ] B: Leave it in place (verified: it already calls `call_claude` zero times on a normal day, since the laptop's copy of these files won't exist — `skills/improve/scripts/cross_machine_merge.py:364-367` checks `.exists()` on both sides first) and remove it in a separate follow-up ticket.
```

---

## Tests to write first

Reusing the existing `test_brief_fallback.py`'s pattern (injected `run=` stub for SSH, real local `sh -c` for the shell-quoting tests — never a string-equality mock there) — this file is already correct and doesn't need to change:

**Per "How we'll try to break it":**
1. `test_mini_down_all_morning_laptop_builds_once` — already present, passes.
2. `test_laptop_waits_before_the_deadline` — already present, passes.
3. `test_toctou_recheck_uses_produced_not_exists` family — already present in `test_brief_fallback.py`/`test_morning_brief.py`; **new**, must add the equivalent to `test_daily_digest.py`/`test_run_colony.py` once the gate order is corrected (see task list) — assert the pre-write recheck fires without re-triggering a second remote SSH call (assert the `run=` stub's call count, not just the outcome — this is the test that would have caught the redundant-double-SSH-call shape).
4. `test_pre_write_recheck_catches_remote_only_produced_during_generation` — already present, passes.
5. `test_failure_placeholder_counts_as_not_produced`, `test_empty_local_file_counts_as_not_produced` — already present, pass.
6. `test_clock_skew_never_compares_across_machines` — already present, passes.
7. Both machines at the same moment — no new test; `is_primary()` is a pure function, nothing to race.

**New, specific to the defects found here (not in the prior design doc, required to actually catch the regression):**
8. `test_main_does_not_regenerate_when_out_file_already_exists_as_primary` (`test_daily_digest.py`) — monkeypatch `machine_profile.registry_id` to `"mac-mini-test"` (primary), write a valid `OUT_FILE`, patch `call_claude`/`roadmap_summary`/etc. to raise-on-call sentinels (reuse the existing `test_main_short_circuits_when_out_file_exists`'s own sentinel pattern rather than deleting that test — fix the production code so the **existing** test passes unmodified). Equivalent for `research_digest.generate()` and `run_colony.main()` (new — `source_monitor.main`/`correlate` must not be called either).
9. `test_write_text_contains_no_undefined_marker_reference` — a smoke test that calls `main()` end-to-end (primary, no existing output, `call_claude` stubbed to return fixed content) and asserts `OUT_FILE.read_text()` starts with the actual header, not a `NameError` traceback. Proves defect #1 is gone.
10. `test_suite_wide_isolation_blocks_real_ssh_by_default` — in each of the three now-affected test directories, a test that calls the entry point (`main()`/`generate()`) with the autouse fixture left at its default (no explicit monkeypatch of `brief_fallback`/`machine_profile`) and asserts, via a module-level counter or a patched `subprocess.run` that raises `AssertionError` if invoked with `"ssh"`, that **zero** real subprocess SSH calls happen. This is the test that would have caught the actual regression; every other new test in the prior attempt used an injected `run=`, but none proved the *default*, unmocked path used by every *pre-existing* test was safe.
11. `test_registry_lookup_failure_treated_as_not_produced` — already present, passes.
12. `test_device_id_resolution_failure_falls_open_to_fallback` — already present (`should_run`'s `try/except` around `registry_id()`), passes.
13. `test_read_remote_quotes_against_shell_injection` — already present (real `sh -c`), passes.
14. `test_unreadable_local_file_falls_through_to_remote` — already present, passes.
15. `test_same_day_idempotent_across_repeated_calls` — already present, passes.
16. `test_check_brief_builder_reports_the_machine`/`_yellow_`/`_red_after_both_deadlines_pass`, `test_job_placement_reflects_the_new_ownership` — already present, pass (verified `check_brief_builder()` touches no I/O, no isolation risk).
17. CONTEXT.md: no test — already correctly edited.

**Verify fails when code changes without a test changing:** run only the touched files — `pytest lib/tests/test_brief_fallback.py lib/tests/test_morning_brief.py lib/tests/test_health_checks.py lib/tests/test_cron_health.py skills/improve/scripts/tests/test_daily_digest.py skills/research-colony/scripts/tests/test_run_colony.py` — not the full `lib/tests/` directory (the before/after metrics comparison already re-runs the full suite; an unscoped run here is exactly the unbounded step that correlates with this ticket's repeated timeouts). Confirm test #8, #9 and #10 each fail against the current dirty-worktree code (not against clean `main`, since `main` has no gate at all) and pass after the fix.

---

## Task List

1. **Fix defect #1** — `skills/improve/scripts/daily_digest.py:335`: remove the stray `marker +` prefix; restore `OUT_FILE.write_text(header + health_section + content + "\n")`.
2. **Fix defect #2 in `daily_digest.py::main()`** — reorder: keep the `should_run()` call first (unchanged), then add `if OUT_FILE.exists() and brief_fallback.produced(OUT_FILE): skip` immediately after it (restores the old short-circuit, now content-aware), then generate, then keep the existing pre-write `produced()` recheck before `write_text`.
3. **Same fix in `research_digest.py::generate()`** — add the `out_path.exists() and brief_fallback.produced(out_path)` guard right after the `should_run`-equivalent gate (currently just `if brief_fallback.produced(out_path):` with no `.exists()` short-circuit guard — add it so an absent local file never triggers a remote SSH check at this point) and before the fetch/correlate work starts.
4. **Same fix in `run_colony.py::main()`** — add `if out_path.exists() and brief_fallback.produced(out_path): skip` right after the existing `should_run()` gate check, before `source_monitor.main()` runs, so the fetch/correlate steps aren't wastefully re-run on a day the digest is already written.
5. **Fix defect #3 — test isolation.** Add one new autouse fixture to `lib/tests/conftest.py`:
   ```python
   @pytest.fixture(autouse=True)
   def _isolate_machine_role(monkeypatch):
       # brief_fallback.should_run() resolves this machine's role via machine_profile.registry_id(),
       # which reads the real ~/.claude registry and, off the primary, can SSH a real peer.
       # Default every test to primary (the old, gate-less behavior); a test opts into the
       # standby path by overriding this or by passing device_id explicitly.
       import machine_profile
       monkeypatch.setattr(machine_profile, "registry_id", lambda: "mac-mini-test")
   ```
6. Create `skills/improve/scripts/tests/conftest.py` and `skills/research-colony/scripts/tests/conftest.py`, each with the identical fixture from step 5 (no existing conftest.py in either directory to extend).
7. Add test #8 (both variants), #9, #10 (three variants) from the "Tests to write first" list above, to `lib/tests/test_brief_fallback.py`'s sibling test files as named.
8. Edit `skills/improve/scripts/tests/test_daily_digest.py`'s existing `test_main_short_circuits_when_out_file_exists` — leave it textually unchanged; confirm (don't modify) that it now passes once steps 1–2 land. If it still fails after step 2, that's a sign step 2's ordering is wrong, not a reason to weaken the test.
9. Leave untouched (already correct, verified by direct read): `lib/brief_fallback.py`, `lib/tests/test_brief_fallback.py`, `lib/morning_brief.py`, `lib/tests/test_morning_brief.py`, `lib/health_checks.py`, `lib/tests/test_health_checks.py`, `lib/cron_health.py`, `CONTEXT.md`, all four `.plist` files, `skills/research-colony/scripts/tests/test_run_colony.py`.
10. Run only the targeted files listed under "Verify fails when code changes without a test changing" above; confirm each new/changed test fails against the current dirty-worktree code and passes after steps 1–6.
11. Add the Decisions section above to the PR body, unanswered.
12. In the PR description, state plainly: (a) `cross_machine_merge.py` is untouched pending the `retire-cross-machine-merge` Decision; (b) the actual Mini/MacBook launchd install-location swap is a manual `launchctl bootstrap`/`bootout` step on each physical machine that this diff cannot perform — until done, AC1 isn't in effect on the ground, only ready to be made effective; (c) name the three root-cause defects found and fixed (undefined `marker`, the dropped primary short-circuit, the missing test-isolation fixture), since that's the actual explanation for the prior "regressed/mixed" verdict, not a restatement of the previous (incorrect) diagnosis.
13. Surface item 12(b) directly, not only in the PR body — it's a step Gil must finish by hand.
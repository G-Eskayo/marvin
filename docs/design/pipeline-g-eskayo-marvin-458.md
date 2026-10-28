## North-star fit

**Reuses before adding anything new:** confirmed by reading the live code, not trusting either prior design doc's self-description. `lib/scanner_role.py:23,27` (`PRIMARY_PREFIX = "mac-mini"`, `is_primary(device_id) = device_id.startswith(PRIMARY_PREFIX)`) and `lib/machine_profile.py:161,175,186` (`machine_label()`, `registry_id()`, `remote_devices()`) are the real, already-existing primary/standby primitives this ticket's fallback gate reuses — the preserved WIP at rescue ref `refs/rescue/pipeline/g-eskayo/marvin#458/20261022T110641735890Z` (commit `40411cef`, "WIP preserved before redispatch") builds `lib/brief_fallback.should_run()` directly on top of them rather than inventing a parallel mechanism, mirroring the shape of `scanner_role.should_scan()` (its own docstring says so, and the call pattern matches). I verified `git diff 40411cef^ HEAD -- <all 9 touched source/doc files>` is still empty — none of them have drifted since the WIP was cut — so the WIP's diff is current, not stale.

**Root cause of the "unchanged / failing" result, found by investigation, not assumed:** the prior design doc's Task List step 1 was `git cherry-pick 40411cef`. The current worktree has **no `lib/brief_fallback.py`** (confirmed: `Glob lib/brief_fallback.py` → no files) — the cherry-pick never happened, which is exactly consistent with "unchanged" across every single metric (pytest/vitest passed/failed delta = 0): nothing was ever written. Looking at the one implementation prompt visible in this ticket's own comment history (the 900s-timeout one), the agent's `--allowedTools` list is `Read,Edit,Write,Bash(graphify query*),Bash(gh issue view/list/pr view/list/diff/checks*),Bash(git status/log/diff/show/blame/ls-files/rev-parse/grep*),Bash(pytest/python -m pytest/npm test/npx vitest*)` — **no `git add`, `git commit`, `git cherry-pick`, or `git apply` anywhere in it.** My own permissions for this very planning task are the same shape (read-only `git log/diff/show/blame`, no mutation). This is a structural constraint on every implementation agent in this pipeline, not a one-off: **it can only change files via `Read`/`Edit`/`Write`, never git plumbing.** A plan whose task list opens with "cherry-pick a commit" is therefore not executable — the tool call has nowhere to land, and the agent either errors out immediately or (per the timeout) stalls trying to work around it. This is the defect in the prior plan, and the fix is mechanical: **materialize the exact same content via `Write`/`Edit`, never `git`.**

**Simplest sufficient approach, unchanged in substance:** restore the already-correct ~1,330-line WIP (new files via `Write`, existing-file diffs via `Edit` with exact anchors I pulled from `git diff 40411cef^ 40411cef -- <file>` for every touched file), add the one genuinely-missing test, delete the one dead line, skip re-running the full suite (the pipeline's own metrics comparison already does that after this attempt — re-running it here is exactly the kind of step whose cost may have contributed to the 900s wall before). I independently re-verified, reading `git show 40411cef:lib/brief_fallback.py` and `git show 40411cef:lib/tests/test_brief_fallback.py` directly, that both prior-claimed-open defects (`_infer_remote_path` subdirectory-dropping, `read_remote` over-quoting `$HOME`) are in fact already fixed in that commit's code, and the corresponding tests (`test_infer_remote_path_preserves_subdirectory`, `test_infer_remote_path_falls_back_to_filename_outside_home`, `test_read_remote_lets_home_expand_but_quotes_rest`, `test_read_remote_quotes_against_shell_injection`, `test_unreadable_local_file_falls_through_to_remote` with `try/finally`) already exist. The WIP's own bundled design doc, which claims these are still open, is itself the stale artifact — confirmed by reading code, not description.

**Where this saves/spends tokens:** this is ADR 0067's "halve the model calls" ticket — once the Mini's launchd jobs are installed, `daily-digest`/`research-colony`/`morning-brief` each run once, not twice, and `~/.claude` sync stops seeing duplicate same-day quarantine entries (the exact 2026-10-10/2026-10-15 incidents ADR 0067 §Context names). Materializing known-good content via `Write`/`Edit` is a bounded, mechanical pass — cheaper than re-deriving the logic, and cheaper than the previous plan's git-plumbing dead end plus a full-suite re-run.

**More capable or more passive:** more capable — Health gains a real "which machine built today's brief" answer (AC4) instead of silence, and the duplicate-quarantine noise that was landing on Gil's own sync stops.

**ADR/CONTEXT check:** `CONTEXT.md:1442`'s "Brief owner" bullet is corrected by this same WIP diff to state the three schedule times and that `cross_machine_merge.py`'s step is wired but runs zero LLM calls on a normal day — matches ADR 0067 Consequences ("fan-out-and-merge becomes unnecessary for these jobs") without silently removing the code, which is right given the open Decision below. Not touching the older "Fan-out + merge (mode 2)" section (`CONTEXT.md:189–218`, the 2026-07-08 [[0014]] decision) — reconciling that text is a documentation cleanup outside this diff, not a defect this ticket introduces.

**Known limitation, flagged not fixed:** `scanner_role.is_primary()`'s `startswith("mac-mini")` would also match a future `mac-mini-2012` (Kali) node if it ever ran these jobs; it won't today (untagged/general jobs vs. that node's `security`/`quarantine`/`test`/`bench` tags), so this is a pre-existing, out-of-scope risk inherited from `scanner_role.py`, not introduced here.

---

## Decisions

Both carried over unchanged — genuinely unresolved, not required to satisfy the 4 acceptance criteria, must ship as a structured Decisions block per `docs/agents/decisions-format.md`, not prose:

```markdown
## Decisions
<!-- marvin:decisions -->
### quarantine-counts-as-produced: Does a quarantined (but not failed) digest count as "the Mini produced it"?
The restored code implements option A. Please confirm or override.
- [ ] A: Quarantined counts as produced — the Mini did its job; a held-back item is a safety-check outcome, not an outage. The laptop never rebuilds just because content got quarantined.
- [ ] B: Quarantined counts as not produced — if the brief chain got nothing usable, the laptop should still try, in case its own run clears the safety check.

### retire-cross-machine-merge: Remove `cross_machine_merge.py`'s LLM digest/research-digest merge step now, or leave it in place?
- [ ] A: Remove `run_merge_authority` and its daily-digest/research-digest loop now — ADR 0067 says this step "becomes unnecessary for these jobs," and leaving it risks a stray LLM merge call + a third `{day}-merged.md` write-back on the rare day the fallback actually fires.
- [ ] B: Leave it in place for now (it already runs zero LLM calls on a normal day, since one side's file won't exist) and remove it in a separate follow-up ticket.
```

---

## Tests to write first

All content below already exists, verified by reading `git show 40411cef:<path>` directly, except item 4 (genuinely new). Against the real collaborator pattern this suite already uses: `monkeypatch`/`tmp_path` for the filesystem, an injected `run=` callable for SSH, and a real local `sh -c` for the shell-quoting tests (string-equality mocks can't prove actual shell-expansion — that's how the `$HOME`-quoting bug escaped review before).

**Per "How we'll try to break it":**
1. `test_mini_down_all_morning_laptop_builds_once` — Mini down all morning: fallback builds once, logs "fallback: covering for the primary"; second call sees it produced and doesn't rebuild.
2. `test_laptop_waits_before_the_deadline` — Mini late but inside grace: standby does nothing, never touches SSH (the `run` stub raises `AssertionError` if called).
3. `test_toctou_recheck_uses_produced_not_exists` (`test_daily_digest.py`) + `test_research_digest_toctou_uses_produced` (`test_run_colony.py`) + `test_write_is_idempotent_against_an_existing_file` (`test_morning_brief.py`) — Mini finishes **after** the MacBook already started generating: the pre-write recheck catches it and the standby's write is dropped.
4. **New, not in the WIP:** `test_pre_write_recheck_catches_remote_only_produced_during_generation`, in `lib/tests/test_brief_fallback.py` — calls `brief_fallback.produced()` twice with no local file ever created, using a stateful `run=` stub that returns "not found" on the first call and real content on the second, both via the same `remote_path`. Needed because every existing TOCTOU test simulates the primary finishing via a **local** file appearing; none exercise the primary finishing via the **live remote SSH signal alone** flipping between the gate check and the pre-write recheck — the actual mechanism for a genuinely cross-machine (not same-filesystem) race. Placed directly against `produced()` rather than through `daily_digest.main()`/`run_colony.main()` because those callers invoke `brief_fallback.produced(OUT_FILE)` with no `run=` injection point of their own — testing at the function that actually owns the race is the simplest sufficient place, not a design change.
5. `test_failure_placeholder_counts_as_not_produced`, `test_empty_local_file_counts_as_not_produced` — Mini's output exists but is a failure placeholder or empty: counts as not produced.
6. `test_clock_skew_never_compares_across_machines` — `past_deadline()` is local-wall-clock-only by signature (`__code__.co_varnames` has no `device_id`/`remote`), never compares against the remote's clock.
7. Both machines at the same moment: no new test — confirmed by reading that the primary's branch of `should_run()` is a pure function of `device_id` (`is_primary()` → immediate `True`, zero I/O), so there is no shared mutable state for two concurrent calls to race on.

**Misuse not named in the ticket but required by the standing TDD bar:**
8. `test_registry_lookup_failure_treated_as_not_produced` — `machine_profile.remote_devices()` raising (bad/missing `marvin-network.json`) is caught, treated as "not produced," never a crash.
9. `test_read_remote_quotes_against_shell_injection` — adversarial path (`; rm -rf /` etc.) run through a real local `sh -c`; asserts no injected side effect ever executes.
10. `test_same_day_idempotent_across_repeated_calls` — repeated same-state calls never flap.
11. `test_check_brief_builder_reports_the_machine` / `test_check_brief_builder_yellow_when_nothing_built_yet` / `test_job_placement_reflects_the_new_ownership` — Health's AC4 surface, both states, plus `JOB_PLACEMENT` ownership assertions.
12. **CONTEXT.md:** no test — a one-sentence doc correction, not code.

**Verify fails when code changes without a test changing:** the implementation step must run only the targeted files it just wrote/edited (`lib/tests/test_brief_fallback.py`, `lib/tests/test_morning_brief.py`, `lib/tests/test_health_checks.py::test_check_brief_builder*` and `::test_job_placement*`, `skills/improve/scripts/tests/test_daily_digest.py`, `skills/research-colony/scripts/tests/test_run_colony.py`) via the already-allowed `pytest <specific file>` pattern — not the full `lib/tests/` directory (135 files; an unscoped full-suite run is exactly the kind of unbounded step that may have contributed to a prior 900s timeout, and the pipeline's own before/after metrics comparison already re-runs the full suite after this attempt, so doing it again here is redundant work this ticket shouldn't spend). Confirm each new/changed test fails before the corresponding file is written (by running it against current `HEAD`, where `lib/brief_fallback.py` doesn't exist at all) and passes after.

---

## Task List

Every step uses only `Read`/`Edit`/`Write` plus read-only `Bash(git show 40411cef:<path>)`/`pytest <file>` — no `git add`/`commit`/`cherry-pick`/`apply`, since those tools are not available to the implementation agent (the actual defect in the prior attempt).

1. `Write lib/brief_fallback.py` with the content from `git show 40411cef:lib/brief_fallback.py`, **minus** the unused `PRIMARY_PREFIX = "mac-mini"` module-level line (dead duplicate of `scanner_role.PRIMARY_PREFIX`, never referenced in the file).
2. `Write lib/tests/test_brief_fallback.py` with the content from `git show 40411cef:lib/tests/test_brief_fallback.py`, plus the new `test_pre_write_recheck_catches_remote_only_produced_during_generation` (test 4 above) appended to `TestProduced`.
3. `Write skills/improve/scripts/tests/test_daily_digest.py` and `Write skills/research-colony/scripts/tests/test_run_colony.py` with the content from `git show 40411cef:<path>` (both new files).
4. `Edit lib/tests/test_health_checks.py` and `Edit lib/tests/test_morning_brief.py`, appending the new test functions shown in `git diff 40411cef^ 40411cef -- lib/tests/test_health_checks.py lib/tests/test_morning_brief.py` (anchor on the last existing line of each file; both diffs are pure additions).
5. `Edit lib/morning_brief.py`: apply the diff from `git diff 40411cef^ 40411cef -- lib/morning_brief.py` — add the `builder_reason` parameter and idempotency check to `write()`, add `build()`, add `builder_of()`, change `__main__`'s `["build"]` branch to call `build()`.
6. `Edit lib/health_checks.py`: apply the diff from `git diff 40411cef^ 40411cef -- lib/health_checks.py` — change `JOB_PLACEMENT`'s `daily-digest`/`research-colony` entries from `"both"` to `"mini"` plus the three new `*-fallback: "laptop"` entries, change `morning-brief` from `"laptop"` to `"mini"` plus its fallback entry, add `check_brief_builder()`, register it in `default_checks()`.
7. `Edit lib/cron_health.py`: add the `"morning-brief": ("09:15", [...])` entry to `JOBS`, per the diff.
8. `Edit skills/improve/scripts/daily_digest.py`: add the `brief_fallback` import and the gate check + TOCTOU recheck in `main()`, per the diff.
9. `Edit skills/research-colony/scripts/research_digest.py`: add the `brief_fallback` import, change `out_path.exists()` to `brief_fallback.produced(out_path)`, add the pre-write TOCTOU recheck, per the diff.
10. `Edit skills/research-colony/scripts/run_colony.py`: add the `brief_fallback` import and the gate check in `main()`, per the diff.
11. `Write config/launchd/com.marvin.morning-brief-fallback.plist`, `Write skills/improve/com.marvin.daily-digest-fallback.plist`, `Write skills/research-colony/com.marvin.research-colony-fallback.plist` with the exact content from `git show 40411cef:<path>` (three new files).
12. `Edit config/launchd/com.marvin.morning-brief.plist`, `Edit skills/improve/com.marvin.daily-digest.plist`, `Edit skills/research-colony/com.marvin.research-colony.plist`: apply the comment/schedule-time edits from `git diff 40411cef^ 40411cef -- <path>` (morning-brief moves 09:45→09:15; the other two gain a clarifying comment only, same `StartCalendarInterval`).
13. `Edit CONTEXT.md` at the "Brief owner" bullet (around line 1442): replace the current two-sentence bullet with the revised text from `git diff 40411cef^ 40411cef -- CONTEXT.md`, stating the three schedule times and that the cross-machine-merge step is wired but runs zero LLM calls on a normal day, pending the open `retire-cross-machine-merge` Decision.
14. Add the Decisions section above to the design doc / PR body, unanswered (not pre-ticked).
15. Run only the targeted test files listed in "Verify fails when code changes without a test changing" above (not the full `lib/tests/` suite) and confirm each new/changed test fails against pre-step-1 `HEAD` and passes after steps 1–13.
16. In the PR description, carry forward as still true: (a) `cross_machine_merge.py` is untouched pending the `retire-cross-machine-merge` Decision; (b) **the actual Mini/MacBook launchd install-location swap is a manual `launchctl bootstrap`/`bootout` step on each physical machine that this diff cannot perform** — until Gil (or a follow-up with device access) runs it, AC1 isn't actually in effect even after merge, only ready to be made effective.
17. Surface item 16(b) to Gil directly, not only in the PR body — a fix he must finish by hand doesn't get left in docs alone.
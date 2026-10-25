## North-star fit

**Existing pattern reused (no new primitive):** this attempt's worktree already contains `lib/brief_fallback.py`, built on `lib/scanner_role.py`'s `(bool, str)` primary/standby shape, composing `machine_profile.registry_id()`/`remote_macs()`, `task_dispatch.SSH_OPTS`, and `scanner_role.is_primary()` directly rather than re-deriving the predicate. I read every file this ticket touches before planning, not the stray design docs sitting in the tree. That reading shows the design is sound and ~90% already correct — the job left is closing the specific gaps code review found, not a rewrite.

**Current state, verified by reading, not assumed:** of the three `fix_these` items in the review:
1. **`_quote_remote_path` still uses `subprocess.list2cmdline`** (`lib/brief_fallback.py:50-58`) — confirmed still broken. `list2cmdline` is Windows argv quoting; it only wraps args containing a space/tab and uses double quotes, so `; rm -rf /tmp/pwned` sails through unescaped to the remote `sh -c`. Needs `shlex.quote()`.
2. **`morning_brief.py` missing `json` import** — **already fixed**: `import json` is at module level (`lib/morning_brief.py:18`), and `build()` uses it correctly. The review's finding predates this worktree's current state. I'll still add a regression test per instruction, and leave it otherwise alone.
3. **`build()` doesn't route through `write()`'s `produced()` guard** — confirmed still broken (`lib/morning_brief.py:341-357`). On the Mini, `should_run()` always returns `(True, "primary")`, and `build()` then calls `path.write_text(render(...))` directly, bypassing `write()`'s `brief_fallback.produced(path)` check entirely. Every launchd retry, manual kickstart, or re-run on the Mini silently regenerates and overwrites an already-valid brief and its `.built-by` sidecar.

**Simplest sufficient fix:** make `build()` call `write()` instead of duplicating its write logic — one-line substitution, not new machinery. This also closes a second real gap for free: `daily_digest.main()` and `research_digest.generate()` already have an explicit pre-write TOCTOU recheck (`brief_fallback.produced(...)` called a second time right before the write); `morning_brief.py` has no equivalent today. Routing `build()` through `write()` gives it the exact same recheck shape `write()` already owns, with no duplicate logic.

While in the same functions, I'm also closing three cheap review *notes* (same Watts-check reasoning the prior attempt used: fixing them now avoids reopening the same function twice):
- `check_brief_builder()`'s single 70-min `past_deadline()` call makes it yellow ("fallback may still build") from midnight on, including hours before the brief is even scheduled, and never distinguishes "fallback's own building window" from "genuinely late." Splitting into two `past_deadline()` calls (grace=60, grace=70) plus a "not yet due" branch fixes both.
- `should_run()` ignores any injected clock, unlike `check_primary(now=None)`/`check_brief_builder(now=None)` elsewhere in the codebase — makes deadline-dependent paths untestable without monkeypatching `datetime` globally. Adding an optional `now` parameter matches the established convention.
- `config/launchd/com.marvin.morning-brief.plist:5`'s comment says the fallback runs "60min after primary deadline+grace window" — it actually runs 5 min after (10:50 vs. 10:45). One-line fix.

**Not fixing:** `docs/screenshots/vitals-v4/data.js` still hard-codes `/Users/gileskayo`, which fails `lib/tests/test_no_hardcoded_home.py::test_no_code_hard_codes_the_mac_home_directory` — confirmed still present, committed on `main` at `6b4f5c47` ("docs: Vitals v4"), completely unrelated to this ticket. This will keep failing the merge gate for *any* PR, including this one, until someone fixes it separately. I'm surfacing it, not fixing it here — it's out of scope and touching it would be unrelated scope creep.

**Cleanup:** `docs/design/pipeline-g-eskayo-marvin-458.md` and `-tasks.md` are untracked scratch files a prior pipeline attempt left in the tree — the leftover-chatter/duplicated-task-list the review flagged. Deleting them, not shipping them.

**Tokens:** this is ADR 0067's "halve the model calls" ticket. The fix is corrective, not additive — same file set, no new module. Once `build()` stops double-writing, repeated launchd retries on the Mini cost zero extra model calls (there are none in `morning_brief.py` anyway; the saving is daily-digest/research-colony running once instead of twice daily, which the existing `brief_fallback.produced()` gates already in place deliver).

**More capable, not more passive:** Health (AC4) gets an honest, non-misleading "which machine, and how worried should I be" signal across the full day instead of a yellow that fires overnight for no reason.

## Decisions

<!-- marvin:decisions -->
### retire-cross-machine-merge: Remove `cross_machine_merge.py`'s LLM digest/research-digest merge step now, or leave it for a follow-up?
- [ ] A: Remove `run_merge_authority()`'s daily-digest/research-digest loop (`skills/improve/scripts/cross_machine_merge.py:350-358`) now — ADR 0067 says this step "becomes unnecessary," and leaving it risks a stray `{day}-merged.md` write on a day the fallback and a late primary both produce output.
- [ ] B: Leave it in place (it already costs zero LLM calls on a normal day, since one side's file won't exist once only the Mini writes) and remove it in a separate ticket.
<!-- /marvin:decisions -->

Not reopened: `quarantine-counts-as-produced` (checked the actual code — a quarantined digest contains no `(claude call failed:` marker, so `produced()` already returns `True` for it; matches ADR 0067's "never blocks the whole brief" philosophy) and `brief-schedule-margin` (CONTEXT.md already records the schedule times as decided, matching all four plists byte-for-byte).

## Tests to write first

Pattern reused throughout: `tmp_path`/`monkeypatch`, an injectable `run=` for SSH (never string-equality mocking of `subprocess.run` — that's how the quoting bug shipped), a real local `sh -c` for the injection test, explicit `now=` instead of wall-clock.

**Regression tests for the must-fix defects:**
1. `test_quote_remote_path_without_home_prefix` / `test_quote_remote_path_with_home_prefix_only_quotes_the_suffix` — rewritten to assert exact `shlex.quote()`-equivalent output (the current assertions are too weak to fail against `list2cmdline`).
2. `test_read_remote_quotes_against_shell_injection` — a path containing `; touch <sentinel>` run through a real `sh -c` via the `run=` stub; asserts the sentinel is never created. Fails against current `HEAD`, passes after `shlex.quote()`.
3. `test_read_remote_still_expands_home` — a `$HOME/...` path run through real `sh -c` with `env={"HOME": tmp_path}`, confirming `$HOME` still expands while the rest is quoted.
4. `test_build_writes_valid_json_sidecar` — `build()` once, `json.loads()` the sidecar, assert `builder`/`at`/`reason` keys. Would have caught the (already-fixed) `NameError`.
5. `test_build_on_primary_does_not_overwrite_an_existing_brief` — `build()` called twice with `should_run` mocked `(True, "primary")`; `render`/`gather` are call-counted and must fire exactly once; the `.built-by` timestamp is byte-identical across both calls. **Fails against current `HEAD`** (today's code re-renders and re-stamps every call).
6. `test_build_recheck_catches_a_concurrent_write` — pre-populate the brief file with valid content, mock `should_run` `(True, "primary")`, monkeypatch `render` to raise if called; `build()` must leave the pre-existing content untouched.

**From the ticket's "How we'll try to break it":**
7. `test_fallback_builds_once_then_stays_idle` — no Mini output all morning: `should_run()` on a standby id past deadline+grace returns `(True, ...)`; after the fallback writes the file, a second `should_run()` call returns `(False, "already produced locally")` and makes no SSH call.
8. `test_toctou_recheck_drops_the_write_when_primary_finishes_mid_generation` (new, `TestDailyDigestGate`) — `brief_fallback.produced` stubbed `side_effect=[False, True]` (simulating the primary finishing between the initial check and the write); `daily_digest.main()`'s write never happens.
9. New file `skills/research-colony/scripts/tests/test_research_digest.py::test_toctou_recheck_drops_the_write` — same shape against `research_digest.generate()`, which has zero test coverage today despite already having the recheck in code.
10. `test_check_brief_builder_not_yet_due_before_primary_deadline` — green before deadline+60 (replaces the current "yellow at +45min" assertion, which the fix makes green).
11. `test_check_brief_builder_yellow_within_the_fallbacks_own_window` — yellow between deadline+60 and deadline+70 (closes "goes red while the fallback is legitimately covering").
12. `test_clock_skew_never_compares_across_machines` — `past_deadline.__code__.co_varnames` contains no remote-clock parameter; regression guard.
13. `test_concurrent_should_run_calls_are_independently_safe` — two threads calling `should_run()` with identical mocked IO and no shared mutable state; both return the same consistent answer, no exception, no lock needed (same philosophy `scanner_role.py` already states).
14. MacBook asleep through the deadline: covered by #7 (pure function of elapsed time; no new test needed).

**Verify fails when code changes without a test changing:** run only
`~/.agents/venv/bin/python -m pytest lib/tests/test_brief_fallback.py lib/tests/test_morning_brief.py lib/tests/test_health_checks.py -k brief_builder skills/improve/scripts/tests/test_daily_digest.py::TestDailyDigestGate skills/research-colony/scripts/tests/test_run_colony.py skills/research-colony/scripts/tests/test_research_digest.py -v` — never the full `lib/tests/` directory. Confirm every new/rewritten test fails against current worktree `HEAD` before its fix and passes after.

## Task List

1. Delete `docs/design/pipeline-g-eskayo-marvin-458.md` and `docs/design/pipeline-g-eskayo-marvin-458-tasks.md` (leftover scratch artifacts, not a deliverable).
2. Edit `lib/brief_fallback.py`: add `import shlex`; rewrite `_quote_remote_path()` to use `shlex.quote()` instead of `subprocess.list2cmdline()`; add an optional `now: datetime | None = None` parameter to `should_run()`, threaded only into the deadline check (default preserves current behavior at all call sites).
3. Edit `lib/tests/test_brief_fallback.py`: tighten the two `_quote_remote_path` tests; add the shell-injection test, the `$HOME`-expansion test, the clock-skew regression guard, the concurrency test, and `test_fallback_builds_once_then_stays_idle`.
4. Edit `lib/morning_brief.py::build()`: replace the direct `path.write_text(render(...))` with a call to `write(now, sources)`; only write the `.built-by` sidecar if it doesn't already exist, so repeated primary invocations stay fully idempotent.
5. Edit `lib/tests/test_morning_brief.py`: rewrite `test_morning_brief_write_with_builder_info` to assert idempotency across two `build()` calls; add the recheck test and the sidecar-JSON test.
6. Edit `skills/improve/scripts/tests/test_daily_digest.py::TestDailyDigestGate`: add the TOCTOU-recheck regression test.
7. Write `skills/research-colony/scripts/tests/test_research_digest.py` (new file): the TOCTOU-recheck regression test for `generate()`.
8. Edit `lib/health_checks.py::check_brief_builder()`: split the single `past_deadline(grace_minutes=70)` call into three tiers (green "not yet due" before +60, yellow between +60 and +70, red after +70).
9. Edit `lib/tests/test_health_checks.py`: replace `test_check_brief_builder_yellow_within_grace`'s +45min assertion with green; add the new +65min yellow case; leave the green-with-builder-info and red-past-+70 tests as-is (still correct).
10. Edit `config/launchd/com.marvin.morning-brief.plist`: fix the line-5 comment ("60min after primary deadline+grace window" → accurate, ~5 min after).
11. Run the scoped verify command above against current `HEAD` (confirm every new/rewritten test fails), then after each edit (confirm green).
12. Carry the `retire-cross-machine-merge` Decision into the PR description, unanswered.
13. State plainly in the PR description, and to Gil directly: (a) the physical `launchctl bootstrap`/`bootout` swap on each Mac is a manual step this diff cannot perform — AC1 isn't live on real machines until that's done; (b) `docs/screenshots/vitals-v4/data.js` (unrelated, pre-existing, committed on `main`) still hard-codes `/Users/gileskayo` and will keep failing `test_no_hardcoded_home.py`'s merge gate on this and every other PR until it's fixed separately.
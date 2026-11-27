## North-star fit

**Reuses, before adding anything new:**
- `brain-map/scripts/work_view.py:249-300` (`_job_state`/`job_workers`) — the existing lazy, pull-based staleness check jobs already use for the **red** "crashed" state (`JOB_CRASHED_S`, `BUILDER_DEAD_S`, `chat_helpers.STALE_S`). The new **grey** "not hearing from it" state is the same idiom (compare `now` to a last-report timestamp, recomputed whenever `work_view.py` runs) extended with a third outcome, not a new mechanism.
- `brain-map/template.html:767-799` (`applyWork`) is the **one** function both the dashboard (fetched via `pollActivity`, template.html:1116-1128) and the wallpaper (pushed via `evaluateJavaScript` from `DesktopLive/main.swift:387-395`, and the Linux host's `desktop-live-linux/host.js`) call to render workers. Putting grey rendering here once gives AC3 (parity) for free — it's the same JS, already shared by three consumers.
- `lib/chat_helpers.py:288-298` / `lib/ticket_stages.py:125-129` (`_nudge_work`/`_nudge_quietly`, monkeypatched in `test_chat_helpers.py:262,277,288`) is the existing "tell the map something happened" pattern. Scheduled jobs don't call it today (only helpers/ticket stages do) — wiring `lib/job_events.py:107-124` (`job_run`) into it is what lets a killed job's absence actually get re-evaluated, since nothing else watches it.
- `brain-map/scripts/work_view.py:430-453` (`write`/`main`, `fcntl.flock`) already serialises concurrent regenerations — reused as-is, no new locking.
- The render loop's `clockNow()` (template.html:1144-1145, already driving pulse/decay) is reused for the feed-level staleness check instead of a new timer, so wallpaper mode (which has no `setInterval`, template.html:1133) still catches a dead writer.
- `dashboard/test/polling_guard.js` (the "triggers over polling" static guard) is a constraint, not something to add to: the design introduces **zero** new `setInterval`/`setTimeout`, so no `ALLOWLIST` entry is needed anywhere.

**Why this is the simplest sufficient approach:** CONTEXT.md's "arm a one-shot deadline... rearm... rather than scanning on a timer" is satisfied two different, minimal ways for the two different failure modes in the acceptance criteria, instead of building one generic scheduler:
1. *One specific job dies* (AC1/AC2) → recomputed lazily, server-side, the next time *anything* triggers `work_view.py` (now including every job's own start/finish, via the `job_run` nudge). No new process, no sleeping timer.
2. *Everything dies, including the writer itself* (AC4) → caught client-side by comparing the render loop's own clock against the last good `work.json`'s `generated_at`, which only advances on a real trigger-driven rewrite. No polling of work.json is added to do this.

**Where it spends vs. saves:** one more `job_run()` call per scheduled job run (already happening; the nudge is a cheap detached Popen, same cost as the existing helper/stage nudges). No new timers, threads, or services. Net: a few lines across 5 existing files, no new files except tests.

**Phone-OS / capability:** makes a real failure (a silently dead background job) visible instead of indistinguishable from "nothing to report" — the thing Gil can't currently tell apart. More capable, not more passive: nothing here replaces a human judgment call.

**Machine scoping:** per-machine by construction — `work_view.py` only ever reads *this* machine's own `~/.claude/logs/jobs/*.json` (job logs are explicitly "Per machine (logs are not synced)", `lib/job_events.py:14`) and compares against *this* machine's own `time.time()`. There is no cross-machine clock comparison anywhere in the design, which is what defuses the clock-skew and sleeping-laptop attacks structurally rather than by a special case.

**Prior-art check:** template.html:870-879 records an earlier, explicit decision to *remove* (not grey) a node when a network device goes offline, for a different reason (an unexpected node reappearing is itself the signal worth noticing). That's a different part of the map (Cross-Machine Network trunk) solving a different problem (anomaly detection); CONTEXT.md's 2026-10-30 "Listening sign" is a separate, later, explicit decision that *this* kind of silence should be visible, not removed. The two don't conflict; both are reused for the part of the map they belong to.

## Decisions

The look needs sign-off per the ticket. Three genuinely open choices (wording and the grey/red split are already pinned by CONTEXT.md, so they're not re-asked):

```markdown
<!-- marvin:decisions -->
### grey-shade: Which grey for "not hearing from it"?
- [ ] A: The flat neutral already used for code edges (`rgba(156,163,175,…)`, template.html:1675) — same tone everywhere, no tie to the region
- [ ] B: A dimmed, desaturated version of the part's own region hue — still shows which region it's in
- [ ] C: A darker grey than B, closer to the map's background (`#0d1117`), so it recedes more

### overall-mark: Where should the map's own "not hearing anything" mark show?
- [ ] A: A small persistent text line, top-left of the map, visible in both wallpaper and dashboard
- [ ] B: In the existing event tray (template.html "event tray", the same place red workers list for dismissal)
- [ ] C: As a new row in the legend

### dismissible: Can a grey part be dismissed like a red one, or does it only clear when the producer reports again?
- [ ] A: Self-clearing only — it's not a failure to acknowledge, just silence; it disappears the moment the producer reports (recommended: matches CONTEXT.md's "Dismiss and mute" section, which only talks about failures)
- [ ] B: Dismissible the same as a red worker, with its own tray entry
```

## Tests first

**From "How we'll try to break it":**
1. `test_feed_staleness_overrides_a_calm_last_write` (template.html/work.test.mjs) — freeze `work.json`'s `generated_at`, let the render clock run past the writer's own quiet window with no new fetch/push: the map must flip to "not hearing anything," never keep showing the last (healthy-looking) snapshot. Covers "kill the activity writer."
2. `test_weekly_job_quiet_for_days_within_window_stays_calm` (test_work_view.py) — a job whose last run finished days ago but within its declared `max_quiet_s` is not drawn at all (today's "idle" behaviour), not grey.
3. `test_clock_skew_between_macs_never_greys_a_live_producer` (test_work_view.py) — construct the scenario where a job's own log timestamp and the "now" passed in are both local to one machine, and prove no code path in `job_workers`/`_job_state` ever reads or compares a peer's clock or timestamp; feed a deliberately "future" timestamp from a different source and show it's never consulted.
4. `test_laptop_only_job_absent_from_minis_logs_never_greys_on_the_mini` (test_work_view.py) — a job catalogued `"machine": "laptop"` with no entry in this machine's `logs` dict (because job logs aren't synced, `lib/job_events.py:14`) stays un-drawn, never grey, regardless of the laptop's sleep state — proving the Mini's other jobs are computed independently.

**From the acceptance criteria:**
5. `test_every_applicable_job_declares_a_quiet_window` (test_job_catalog.py) — every `JOBS` entry with `machine != "none"` has a positive-int `max_quiet_s`, except an explicit, named allowlist of continuous services (desktoplive, dashboard-webhook, dashboard-launch).
6. `test_quiet_window_not_shorter_than_the_jobs_own_schedule` (test_job_catalog.py) — cross-check against `config/jobs/<name>.json`'s `every_s`/`calendar` where that file exists, catching an obviously-wrong window that would make every normal cycle look grey.
7. `test_job_overdue_past_its_window_goes_grey_with_an_age` (test_work_view.py) — last run finished `max_quiet_s + ε` ago, no new run: worker appears with `state: "grey"` and a "not hearing from it · N min" desc.
8. `test_skip_run_resets_the_window` (test_work_view.py) — a job that logs a legitimate no-op/skip run (still a recorded run, per `lib/job_report.py`'s "a run that skips on purpose... stays a pass") close to its deadline stays calm afterwards — the "said sleeping" case, and proof that "rearm on the next event" works.
9. `test_job_run_nudges_the_map_on_start_and_finish` (test_job_events.py, monkeypatching `_nudge_work` as `test_chat_helpers.py:262` does) — every outcome path (`passed`, `failed`, `crashed`, `SystemExit`) triggers exactly one nudge.
10. `test_wallpaper_and_dashboard_render_identical_grey_from_the_same_doc` (work.test.mjs) — feed the same `work.json` through both the fetch-path call and a simulated `evaluateJavaScript`-path call into `applyWork`, assert identical resulting node state/colour.

**Misuse not in the ticket's list:**
11. `test_corrupt_job_log_is_treated_as_no_data` (test_work_view.py) — malformed JSON in `~/.claude/logs/jobs/<name>.json` (already swallowed by `_read_json`'s `except (OSError, ValueError)`) never crashes `job_workers` and never claims grey or healthy without evidence.
12. `test_catalog_entry_missing_max_quiet_s_defaults_to_never_grey` (test_work_view.py) — an older/partial catalog snapshot (upgrade scenario, or a hand-edit mistake) is read with `.get`, not `[...]`, and degrades safely.
13. `test_a_bad_max_quiet_s_value_fails_the_catalog_test_not_the_writer` (test_job_catalog.py) — a string, zero, or negative value is caught by schema validation, never reaches `work_view.py` at runtime.
14. `test_unreadable_job_log_permission_denied_is_no_data` (test_work_view.py) — simulate an `OSError` from a permissions problem; same as corrupt-file handling.
15. `test_truncated_work_json_mid_rewrite_does_not_rearm_or_flip_grey` (work.test.mjs) — a parse failure on one poll must not be read as "fresh data" (don't rearm the quiet clock) and must not immediately flip to "not hearing anything" either, so a mid-write truncation doesn't flicker the overall mark.
16. `test_rapid_repeated_job_runs_do_not_corrupt_or_duplicate_grey_entries` (test_work_view.py, extending the file's existing "50 helpers starting and stopping in a minute" stress test, `brain-map/scripts/test_work_view.py:7`) — many overlapping `job_run`-triggered nudges still produce one coherent, lock-serialised `work.json` (reusing `work_view.py:448-452`'s existing `fcntl` lock).
17. `test_nudge_failure_inside_job_run_never_breaks_the_job` (test_job_events.py) — mirrors `test_chat_helpers.py:288`'s `boom` pattern: a raising `_nudge_work` still lets the job's own run finish and record its real outcome.

## Task List

1. **`lib/job_catalog.py`**: add `max_quiet_s` (positive int seconds, or `None` only for the named continuous-service jobs) to every `JOBS` entry, derived from each job's existing cadence (its `"healthy"` prose and, where one exists, its `config/jobs/<name>.json` schedule).
2. **`lib/tests/test_job_catalog.py`**: add the window-presence test, the continuous-service allowlist test, and the schedule cross-check test (tests 5–6, 13 above).
3. **`work_nudge.quietly()`** (new, in `lib/work_nudge.py`): hoist the `_nudge_work`/`_nudge_quietly` pair currently duplicated in `lib/chat_helpers.py:288-298` and `lib/ticket_stages.py:125-129` into one shared function; update both call sites to use it (small dedup motivated directly by adding a third call site next).
4. **`lib/job_events.py`**: call `work_nudge.quietly()` once when a run starts (next to the existing "appear immediately as running" `_mutate` at line 110) and once when it ends (wrap the `try/except/else` in `job_run` in a `finally`, or add the call at each exit path) — so every scheduled job's start and finish is a trigger the map can react to.
5. **`lib/tests/test_job_events.py`**: tests 9 and 17 above.
6. **`brain-map/scripts/work_view.py`**: extend `job_workers()`/`_job_state()` so a job whose state is currently "idle" (last run finished cleanly or at all, no run in progress) is checked against `now - last_seen > j.get("max_quiet_s")`; emit a `state: "grey"` worker with a `"not hearing from it · N min"` desc when overdue, leave it undrawn (unchanged) otherwise. No change to the existing "failed"/"running" paths.
7. **`brain-map/scripts/test_work_view.py`**: tests 2, 3, 4, 7, 8, 11, 12, 14, 16 above.
8. **`brain-map/template.html`**: extend `applyWork` (line 767-799) to accept a third worker state `"grey"` alongside `"failed"`/`"running"` (line 773), render it in the declared grey (pending Decision), and exclude it from the dismiss tray/`redWorkers()`. Add the feed-level staleness check inside the existing render loop (reusing `clockNow()`, no new timer) comparing against the last-seen `doc.generated_at`, showing/hiding the overall mark (pending Decision on placement).
9. **`brain-map/tests/work.test.mjs`**: tests 1, 10, 15 above, using the existing `window.__map.applyWork` test hook.
10. Generate a screenshot of the new grey state and the overall mark (via `generate.py` + the existing demo/evidence tooling) and attach it to the PR with `marvin-show`, per the ticket's "show it in the #865 mock-up" instruction, alongside the Decisions block.
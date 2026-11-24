## North-star fit

**Reuses before adding anything new:**
- `lib/job_catalog.py`'s `JOB_PLACEMENT` (`lib/health_checks.py:1241-1242`, already "derived from job_catalog so placement is never kept in two places") becomes the coverage denominator's source too — one table, three consumers (placement, waste, coverage), not a second catalog.
- `lib/job_catalog.py`'s own `_loaded_here()` (`job_catalog.py:148-157`) replaces `health_checks.discover_launchd_jobs()`/`_plist_label_to_job_name()` (`health_checks.py:277-297`) for coverage's "what's really running here" side — job_catalog already re-implements the identical launchctl-scan independently; after this change `discover_launchd_jobs`/`_plist_label_to_job_name` have zero remaining callers and get deleted rather than left as dead duplicate code.
- `machine_profile.pull_only()` (`machine_profile.py:186-197`, "An unregistered machine is pull-only unless it is a Mac, so an unknown Linux box is never trusted by default") is the exact precedent for the new `calibrated()` helper's asymmetric default — same shape, same reasoning, so a future second non-Mac node is automatically excluded too, without hardcoding "mac-mini-2012" anywhere.
- `lib/mirror_health.py`'s existing `mirror:sync@<device>` row (built for marvin#910, already merged) stays the one detailed signal for mac-mini-2012; this ticket doesn't duplicate it.
- `_result()` (`health_checks.py:48-50`) is already the `checked_at`-stamping pattern every other check module (`graphify_freshness.py`, `memory_lint.py`, `profile_parity.py`, `stale_relay.py`, `parked.py`) already follows — `output_contracts.py` and `purpose_metrics.py` are the two modules that bypass it with raw dict literals; the fix is to match the existing pattern, not invent a new one.

**Simplest sufficient approach:** every piece here is a same-shape swap (one data source for another) or a one-line addition (`checked_at`), not new machinery. No new state files, no new severities, no new UI components.

**Resource cost:** net code *shrinks* (two duplicate discovery functions deleted); `check_machine_reachability` does fewer SSH probes (skips the uncalibrated device's probe entirely instead of waiting out its timeout).

**Capability:** this is infrastructure truthfulness, not a user-facing capability — it makes Gil *more* able (a red verdict will mean something again instead of being cried-wolf), it doesn't automate a judgment away from him. The one piece that would have automated a judgment (auto-filing a decision ticket when a producer's output goes stale) is deliberately left to Gil via Decision A below rather than guessed.

**Machine:** no machine-specific code; this runs identically on every Mac that runs `health_checks.py`.

## Tests first

One file per concern, matching the repo's existing module-per-test-file convention.

**`lib/tests/test_health_checks.py`**
1. `test_no_cron_check_exists` — no id in `default_checks()` is `"cron"` or starts with `"cron:"`; `hc.check_cron_job_log` and `hc._cron_job_logs` no longer exist (`hasattr` is False); `discover_launchd_jobs`/`_plist_label_to_job_name` no longer exist either (dead-code removal, not just the cron entry).
2. Delete (not rewrite — the functions they test are gone): `test_check_cron_job_log_establishes_baseline_on_first_run`, `test_check_cron_job_log_flags_genuinely_new_failures`, `test_check_cron_job_log_returns_none_for_unmapped_job`, `test_plist_label_to_job_name_strips_known_prefixes`.
3. Rewrite `test_coverage_flags_jobs_with_no_registered_check` / `test_coverage_full_when_everything_discovered_has_a_check` — monkeypatch `job_catalog.loaded_here` (renamed from `_loaded_here`), not `discover_launchd_jobs`; assert `coverage()` takes no `results` arg.
4. `test_coverage_a_catalogued_job_not_loaded_on_this_machine_does_not_inflate_the_denominator` — a "mini"-only job in `JOB_PLACEMENT` that isn't in `loaded_here()`'s output must not count toward `total` on the laptop (regression guard for the bug I caught while designing this: naively unioning the whole catalog into the denominator would make every machine's coverage % wrong).
5. `test_coverage_with_an_empty_job_catalog_flags_everything_loaded_as_unmonitored` — ticket's "empty job catalog" misuse case.
6. `test_verdict_severities_excludes_an_uncalibrated_machines_rows` — fixture registry (`monkeypatch.setattr(machine_profile, "_load_registry", lambda: {...})`, the established pattern from `test_machine_profile_linux.py:72-83`) with one calibrated Mac and one uncalibrated Linux box; a red row id'd `machine:the-linux-box` (and `errors@the-linux-box`) must not turn `overall_severity(verdict_severities(results))` red when every calibrated row is green.
7. `test_verdict_severities_flips_once_the_registry_marks_a_device_calibrated` — ticket's "the 2012 box calibrated mid-run" case: same rows, registry's `calibrated` flips `False→True`, same red row now counts.
8. `test_check_machine_reachability_reports_not_reporting_yet_for_an_uncalibrated_device_and_never_shows_its_host` — monkeypatch `subprocess.run` to raise if called at all (proves no SSH probe runs for it), assert the row's `detail` contains neither the registry's `tailscale_hostname` nor the word unreachable/red; severity is `"yellow"`.
9. `test_check_machine_reachability_still_probes_a_calibrated_device_normally` — guard against the previous test's skip-logic leaking onto real Macs.
10. `test_device_of_parses_at_suffix_and_machine_prefix_ids` — direct unit test of the new `_device_of()` id-parsing helper against every id shape already in the module (`machine:x`, `errors@x`, `repo:sync:~/.claude@x`, `mirror:sync@x`, and a plain id with neither, e.g. `"model:availability"`, which must return `None`).
11. Rewrite `test_missed_purposes_are_red_and_an_unreadable_list_is_yellow` → `test_missed_purposes_are_amber_not_red_and_carry_checked_at` — asserts `"yellow"` (not `"red"`) for a labelled issue, and that `"checked_at"` is present and parseable.

**`lib/tests/test_output_contracts.py`**
12. Rewrite `test_a_producer_nobody_consumed_for_30_days_is_a_removal_candidate` — asserts `"yellow"`, keeps the "removal candidate" text assertion (the decision-lane framing stays in the message).
13. `test_every_evaluate_branch_stamps_checked_at` — parametrized over all four `evaluate()` branches (unmeasured / overdue-yellow / cut-after-days / green) plus the `health_findings()` exception-fallback branch; each result's `checked_at` parses as an ISO timestamp.

**`lib/tests/test_purpose_metrics.py`**
14. Rewrite `test_health_turns_red_for_each_missed_purpose` → `test_health_turns_amber_not_red_for_each_missed_purpose_and_carries_checked_at` — asserts `"yellow"` and a parseable `checked_at` on both the per-ticket row and the all-clear green row.

**`lib/tests/test_job_catalog.py`**
15. `test_loaded_here_is_public_and_main_waste_still_works` — the `_loaded_here→loaded_here` rename doesn't break the `waste` CLI path (`job_catalog.py:160-165`).

**`lib/tests/test_machine_profile_linux.py`** (fixture-registry patterns already live here)
16. `test_calibrated_defaults_true_for_a_mac_with_no_field`
17. `test_calibrated_defaults_false_for_a_non_mac_with_no_field` — mirrors `pull_only()`'s asymmetric default, the ticket's actual mac-mini-2012 case.
18. `test_calibrated_explicit_field_overrides_the_os_default` — both directions (Linux box explicitly `true`, Mac explicitly `false`).
19. `test_calibrated_survives_a_junk_value` — ticket's "a person's mistakes": `"calibrated": "false"` (a truthy *string*), `42`, `None`, `[]` must all fall back to the OS-based default rather than silently coercing to `True`.
20. `test_calibrated_handles_a_missing_or_none_registry_entry` — dependency-failure case: device not in the registry at all / entry is `None`.

## Decisions

<!-- marvin:decisions -->
### contract-severity: `output_contracts.py`/`purpose_metrics.py` currently go red only from staleness/elapsed time, which is exactly what CONTEXT.md's Missed purpose says should instead be a Decision-lane question ("retire a producer, lower a target"). No code anywhere auto-files a ticket from a health check today. Should this ticket add that auto-filing, or ship the amber-not-red severity fix alone and leave the "ask Gil to retire or lower the target" step as a manual read of the (now-yellow, not red) card's text?
- [ ] A: Ship amber-only now; auto-filing a Decision ticket for a stale producer is a separate follow-up ticket
- [ ] B: Build the auto-filing now, reusing `lib/incident_ladder.py`'s or `ticket_promotion.py`'s existing "file a ticket" path

### dashboard-grouping: the Fix section says missed purposes/contracts should show "amber, at the top of the system they belong to" — a grouped, per-"system" placement. `HealthDashboard.jsx`'s Checks grid has no system-grouping concept today (it's a flat list in `default_checks()` order), and the private instance plan doc that defines the Vitals layout in detail (§17, inaccessible from this engine-repo worktree) likely specifies the grouping taxonomy. Build it now from a guessed taxonomy, or ship the severity/checked_at fix in this repo and leave dashboard placement to a follow-up once §17 is available to read against?
- [ ] A: Ship the engine-side fix (severity, coverage, checked_at, calibration) now; dashboard grouping is a separate ticket against the instance repo's plan
- [ ] B: Guess a grouping now (e.g. group by the job's `goal` in `job_catalog.py`) and build it in this PR

## Task List

1. `lib/job_catalog.py`: rename `_loaded_here` → `loaded_here` (public, now cross-module); update its one call site in `main()`.
2. `lib/machine_profile.py`: add `calibrated(info: dict | None) -> bool`, mirroring `pull_only()`'s asymmetric-default pattern (explicit JSON `bool` wins; anything else, including a junk value, falls back to `info.get("os", "macos") == "macos"`).
3. `lib/health_checks.py`: delete `check_cron_job_log`, `_cron_job_logs`, `discover_launchd_jobs`, `_plist_label_to_job_name`, the `import cron_health as ch` line, and the `("cron", "Cron job logs", _cron_job_logs, ...)` entry in `default_checks()`.
4. `lib/health_checks.py`: rewrite `coverage()` to take no `results` argument, sourcing `loaded` from `job_catalog.loaded_here()` and the catalogued set from `JOB_PLACEMENT`; update `run_all()`'s one call site to `coverage()`.
5. `lib/health_checks.py`: add `_device_of(result_id)` and `verdict_severities(results, registry=None)`; change `run_all()`'s overall line to `overall_severity(verdict_severities(results))`.
6. `lib/health_checks.py`: in `check_machine_reachability()`, short-circuit before the SSH probe for any device where `machine_profile.calibrated(info)` is `False`, emitting one `"yellow"` / "not reporting yet (uncalibrated)" row that names neither hostname nor IP.
7. `lib/output_contracts.py`: add `checked_at` to all four `evaluate()` return branches and the `health_findings()` exception fallback; change the CUT_AFTER_DAYS branch's severity from `"red"` to `"yellow"`.
8. `lib/purpose_metrics.py`: add a `now` parameter to `health_findings()` (default `datetime.now(timezone.utc)`, matching `output_contracts.health_findings`'s existing pattern) and stamp `checked_at` on both returned shapes; change the per-ticket severity from `"red"` to `"yellow"`.
9. `lib/job_catalog.py`: update the `"cron-health"` job entry's `"consumer"` field (currently `"Health cron:*"`, now stale) to name the real remaining consumer (the session-start report reading `cron-health.md`, per `cron_health.py`'s own docstring) — `cron_health.py` itself and its launchd job are untouched; only the dead `Health cron:*` reference is corrected.
10. Write/update all tests listed above, confirming each one fails against the pre-change code and passes after.
11. Run the full Python suite (`lib/tests`) and confirm no other test references the deleted functions or the old `"red"` severities.
12. Resolve the two Decisions above (or note Gil's answer if he's already indicated one) before opening the PR.
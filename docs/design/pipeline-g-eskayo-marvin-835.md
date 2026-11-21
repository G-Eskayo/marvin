## North-star fit

**Reuses:** `lib/health_checks.py:guarded()` (the sweep's existing per-check safety wrapper) gets the `checked_at` backfill, instead of touching every producer module individually. `lib/job_catalog.py`'s existing `_loaded_here()` (already filters to `com.marvin.*`/`com.giles.*`, already proven bug-free re: Dropbox/Google plists) becomes `coverage()`'s source, reusing `job_catalog.waste()`'s exact "loaded-but-uncatalogued" idea instead of re-deriving it. `machine_profile.py`'s existing `pull_only()`/`remote_macs()` pattern ("an entry with no field predates it and defaults to X") is the template for the new `calibrated()` helper. `overall_severity()`'s existing neutral-severity exclusion (already used for `"asleep"`) needs zero logic changes — a new `"uncalibrated"` literal is neutral by construction, not special-cased.

**Simplest sufficient approach:** no new files, no new subsystem. Three bug-shaped fixes (coverage's source, checked_at's one choke point, cron:* deletion) plus one new small helper (`calibrated()`) and one new fold step for mac-mini-2012's three per-check rows into one.

**Resources:** net code shrinks (deleting `discover_launchd_jobs`, `_plist_label_to_job_name`, `check_cron_job_log`, `_cron_job_logs`, and the `cron:*` entry — all dead once cron:* is gone) while fixing the checked_at gap in one place instead of N producer files.

**Phone-OS / capability:** none of this is Gil-facing automation; it's a prerequisite so the future Vitals view isn't born red. It leaves the *system* more trustworthy (fewer false reds/greys), not the user more or less capable directly.

**Machine:** no machine-specific code; runs identically wherever `health_checks.py` runs (mini, laptop, and the box's own local sweep).

## Current-state corrections to the ticket's own numbers

The ticket cites `lib/health_checks.py:181-196` and `:1441-1455` and `dashboard/.../HealthDashboard.jsx:42` — those line numbers have drifted (PR #913 already landed and added ~20 lines). Current locations:
- cron log-scan check: `health_checks.py:300-315` (`check_cron_job_log`), wired at line 1947 and 1788-1793 (`_cron_job_logs`).
- Dropbox/Google plist bug: `discover_launchd_jobs()` at `health_checks.py:284-297` globs **all** `com.*.plist`, not just `com.marvin.*`/`com.giles.*`, so `com.google.keystone.*`/`com.dropbox.*` plists inflate `coverage()`'s denominator as fake "unmonitored" jobs.
- Staleness-opacity 0.35 code: `HealthDashboard.jsx:44-46` (`stalenessOpacity`).
- `#910`/PR #913 already shipped `mirror:sync@<device>` and restricted `check_repo_sync_everywhere` to Macs only — its own PR description says "#835 can fold this row into the box's 'not reporting yet' state," confirming this ticket's remaining job for mac-mini-2012 is specifically the fold, not the mirror check itself.
- `#623` (calibrate the box) is **closed without being done** (auto-released by the stale-claim bot, `needs-info` label) — there is no existing "calibrated" signal anywhere in `machine_profile.py` or the registry today. This has to be built new.

## Decisions

<!-- marvin:decisions -->
### d1: Missed-purpose/unconsumed-output red escalation ("blocks something else")
The ticket's Fix says these findings are "red only when they also block something else." No code today marks a ticket or contract as blocking another — GitHub's native `blocking`/`blocked-by` relation exists (visible via `gh issue view --json blocking`) but `purpose_metrics.labelled_issues()` uses the plain REST issues-list endpoint, which doesn't carry it; wiring it needs one extra `gh api`/`gh issue view` call per missed-purpose ticket on every sweep (a GitHub budget cost, tracked by the existing `github:budget` check).
- [ ] Build the `blocking`-based red escalation now (extra GitHub call per flagged ticket/contract each sweep)
- [ ] Ship v1 as **always amber**, no red path, for these two finding types; escalation is a follow-up ticket once the GitHub-call cost is measured

### d2: "Amber at the top of the system it belongs to" — UI placement
CONTEXT.md's Vitals section describes missed purposes surfacing "amber, at the top of that system" inside a future system-grouped Vitals view. That grouping doesn't exist yet — `HealthDashboard.jsx` is still one flat grid with no per-system sections to reuse or extend correctly.
- [ ] Build a system-grouping/pinning approximation now inside the existing flat grid (new, untested UI surface, real risk of the same kind of scope the last two failed attempts may have hit)
- [ ] Leave these as ordinary cards (now correctly amber + `checked_at`) in the existing grid for this ticket; defer "top of system" placement to the Vitals-view ticket that actually builds system grouping
<!-- /marvin:decisions -->

## Tests (written first)

From "How we'll try to break it":
1. `test_jobs_exit_is_red_until_a_real_pass_then_green` — feed `evaluate_machine_state` a failing exit code, then a later sweep's successful exit code for the same job name; assert red→green follows the actual exit code each time, never flips green from silence alone.
2. `test_fold_uncalibrated_device_mid_run` — build the per-device rows (`machine:mac-mini-2012`, `errors@mac-mini-2012`, `mirror:sync@mac-mini-2012`) with a registry marked uncalibrated, assert they fold to one neutral row and don't appear in `overall_severity`'s input; rebuild with the registry marked calibrated and assert the three rows pass through unfolded and do contribute to overall.
3. `test_coverage_ignores_a_catalogued_job_not_loaded_here` — a job catalogued for `machine: "laptop"` is absent from this machine's `_loaded_here()` output; assert it's neither counted in `total` nor flagged `unmonitored`.
4. `test_coverage_with_empty_job_catalog` — `job_catalog.JOBS == {}` with jobs actually loaded; assert every loaded job shows `unmonitored`, `fraction == 0.0` (not a ZeroDivisionError), and `evaluate_job_placement`/`JOB_PLACEMENT` built from an empty catalog don't crash (green, nothing expected).

Plus the misuse cases the section didn't name:
5. `test_coverage_excludes_non_marvin_plists` — regression test for the literal Dropbox/Google bug: a `com.google.keystone.agent.plist`-style loaded label must never appear in `coverage()`'s discovered set (this is really `job_catalog._loaded_here()`'s existing prefix filter, exercised through `coverage()`).
6. `test_no_cron_check_ids_in_default_checks` — `[cid for cid, *_ in hc.default_checks()]` contains no `"cron"` entry, and `hc` no longer exposes `check_cron_job_log`/`discover_launchd_jobs`/`_cron_job_logs` (AC: "No cron:* check exists" as a structural guarantee, not just an absent row today).
7. `test_guarded_backfills_checked_at_when_producer_omits_it` — a check function returning a dict with no `checked_at` key gets one added by `guarded()` (bad/incomplete producer output).
8. `test_guarded_preserves_producer_checked_at` — a producer that already sets `checked_at` keeps its own value (stale state: don't let the choke point mask genuinely old data as fresh).
9. `test_mirror_sync_row_has_checked_at_after_guarded` and `test_contract_and_missed_purpose_rows_have_checked_at_after_guarded` — end-to-end through `run_checks()`/`guarded()` for the three specific producers the ticket calls out (dependency: real producer + choke point together, not the choke point in isolation).
10. `test_calibrated_defaults_false_for_non_mac_true_for_mac` — `machine_profile.calibrated()` against a fixture registry entry with no `"calibrated"` key (person's mistake: forgetting to set it) and one explicitly `"calibrated": true`.
11. `test_contract_and_purpose_missed_are_amber_not_red` (per d1's answer) — `output_contracts.evaluate()`'s overdue/never-consumed branch and `purpose_metrics.health_findings()`'s missed branch return `"amber"`.
12. `test_coverage_survives_a_corrupt_loaded_dict` (malformed input, reusing `job_catalog.waste()`'s own `test_waste_survives_junk_loaded_lists` pattern) — `_loaded_here()` returning non-list/garbage values doesn't crash `coverage()`.
13. `test_fold_uncalibrated_survives_unreachable_device` (dependency failing) — the device is also unreachable (ssh timeout) at the same time it's uncalibrated; folding still produces exactly one row, not zero and not a crash.
14. `test_overall_severity_unaffected_by_repeated_uncalibrated_rows` (repeats) — folding runs twice on an already-folded result list (idempotent, no double-fold/duplicate id).

## Task List

1. `lib/machine_profile.py`: add `calibrated(device_id, registry=None) -> bool` — macOS entries always `True`; others read `registry[device_id].get("calibrated", False)`, injectable `registry` dict for tests.
2. `lib/health_checks.py`: add `fold_uncalibrated_devices(results, registry=None) -> list[dict]` — for each non-Mac device where `calibrated()` is false, replace its `machine:<dev>`, `errors@<dev>`, `mirror:sync@<dev>` rows with one `machine:<dev>` row, severity `"uncalibrated"`, detail naming #623; call it in `run_all()` before `coverage()`/`overall_severity()`.
3. `lib/health_checks.py`: delete `discover_launchd_jobs`, `_plist_label_to_job_name`, `check_cron_job_log`, `_cron_job_logs`, the `("cron", ...)` entry in `default_checks()`, and the now-unused `import cron_health as ch`.
4. `lib/health_checks.py`: rewrite `coverage(loaded: dict | None = None)` to source discovered/unmonitored from `job_catalog._loaded_here()` vs `job_catalog.JOBS` (mirroring `job_catalog.waste()`'s own comparison); update `run_all()`'s call site.
5. `lib/health_checks.py`: extend `guarded()` to backfill `checked_at` (via `_now().isoformat()`) onto any returned row missing it, without overwriting a producer-supplied one.
6. `lib/output_contracts.py`: change the overdue/never-consumed branch's `"red"` to `"amber"` (per Decision d1's answer).
7. `lib/purpose_metrics.py`: change `health_findings()`'s missed-purpose `"red"` to `"amber"`.
8. `dashboard/src/components/HealthDashboard.jsx`: add `amber` and `uncalibrated` entries to `SEVERITY_COLOR`.
9. `dashboard/src/components/HealthDrilldown.jsx`: add `amber`/`uncalibrated` entries to `SEVERITY_LABEL`.
10. `lib/tests/test_health_checks.py`, `lib/tests/test_job_catalog.py`, `lib/tests/test_purpose_metrics.py`, `lib/tests/test_output_contracts.py`: remove the now-invalid cron tests, add the 14 tests above.
11. Run full `lib/tests` suite plus dashboard vitest to confirm no regression (per "Full suites before a hand-merge").
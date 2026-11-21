## North-star fit

**Reuses:** `health_checks.guarded()` (`lib/health_checks.py`) as the single choke-point every check result already passes through — backfilling `checked_at` there (one place) instead of in three separate modules (`output_contracts.py`, `purpose_metrics.py`, `mirror_health.py`) that all currently omit it. Also reuses `job_catalog.JOBS`/`_loaded_here()` (already does exactly this "catalogued vs. loaded" diff for `job_catalog.py waste`) instead of writing a second discovery mechanism, and `machine_profile.py`'s existing registry-field pattern (`pull_only()`, `remote_macs()`: read a field, default safe when absent) for the new `calibrated` field. The existing `overall_severity()` already treats any severity outside `{red, yellow, unknown}` as neutral (that's how `asleep` works today) — so "ignore uncalibrated machines" needs no change to `overall_severity()` itself, only a new neutral severity value threaded through.

**Simplest sufficient approach:** for "contract:*/purpose:missed become amber, red only when they also block something else," the simplest form that captures the real principle is: these two checks never self-escalate to red (cap at yellow); a real blocking consequence already has its own independently-red check elsewhere in the sweep (e.g. `pipeline:breaker`, `main:green`). No new "does this block X" cross-reference engine is needed — that would be new machinery serving the system's own complexity (Watts check), not the actual task.

**Resource cost:** small, targeted diffs in `health_checks.py` (delete ~60 lines of cron absorption, add ~30 lines for coverage/fold/backfill), two one-line severity changes in `output_contracts.py`/`purpose_metrics.py`, one new field + one new function in `machine_profile.py`. No new files, no new subsystem. Net lines removed ≈ net lines added.

**Phone-OS direction:** indirect — this is Vitals' foundation (truthful signal), a precondition for the Vitals view the north stars call for, not itself a phone-facing feature.

**User impact:** more capable — a health dashboard that currently lies (15/58 red, several falsely) actively costs Gil trust and attention; a truthful one lets him act on real signal instead of learning to ignore red.

**Machine:** no preference; this is pure code, runs wherever the sweep runs (mini, primary automation host per ADR 0032).

**Where I checked existing code already covers ticket claims (so no new work needed there):** PR #913 (merged, closes #910) already removed the "two yellow 'sync state unverifiable' cards" for mac-mini-2012 (`check_repo_sync_everywhere` now uses `remote_macs()`, which already excludes the box) and already gives it its own `mirror:sync@mac-mini-2012` row. The "Tailscale IP shows on screen" item also appears stale: the real registry (`~/.claude/marvin-network.json`) already stores `tailscale_hostname: "mac-mini-2012"` (a name, not a raw IP) for that device. I'm not re-doing that work. "A red clears only on a recorded pass, or when the check is retired" is already true structurally — every check recomputes live each sweep; nothing decays a red to green on a timer. No change needed there.

## Tests first (one per break-case, plus misuse the ticket didn't list)

All in `lib/tests/test_health_checks.py` unless noted.

**No `cron:*` check exists**
1. `test_no_cron_check_registered` — `"cron"` is not among the ids in `hc.default_checks()`; `hc.check_cron_job_log`/`hc.discover_launchd_jobs`/`hc._cron_job_logs` no longer exist (attribute error on `hc`).

**Overall verdict ignores uncalibrated machines**
2. `test_overall_ignores_uncalibrated_machine_even_when_its_dependent_checks_are_red` — fixture registry with one device marked `"calibrated": false`; its reachability/mirror rows are red; `run_all`'s (or the fold step's) overall stays unaffected by that device.
3. `test_uncalibrated_machine_folds_dependent_checks_into_one_row` — `machine:<dev>`, `mirror:sync@<dev>`, `errors@<dev>` all collapse into exactly one row (`machine:<dev>`, a neutral severity, "not reporting yet").
4. `test_calibrated_machine_unaffected` — a device with no `calibrated` field (today's real registry shape) behaves exactly as before (regression guard).
5. `test_box_calibrated_mid_run` (the ticket's named break-case) — same fixture flips `calibrated` False→True between two sweeps; first sweep folds and excludes it from overall, second sweep shows its real per-check rows and can affect overall again.
6. `test_is_calibrated_malformed_value_defaults_true` (person's mistake) — `"calibrated": "false"` (a string, truthy in Python) must still count as calibrated; only the literal boolean `false` disables it. (`lib/tests/test_machine_profile.py`)
7. `test_is_calibrated_unreadable_registry_defaults_true` (dependency failing) — corrupt/missing `marvin-network.json` → every device reads calibrated (fail-open, matching `_load_registry()`'s existing behavior). (`lib/tests/test_machine_profile.py`)

**Coverage numerator/denominator come from the job catalog only**
8. `test_coverage_counts_catalogued_jobs_regardless_of_local_load` — a job catalogued for "mini" counts as covered even with an empty `loaded` dict (a catalogued job with no plist on *this* Mac).
9. `test_coverage_flags_locally_loaded_job_not_in_catalog` — a job present in `loaded` but absent from the fixture catalog shows up only in `unmonitored_jobs`.
10. `test_coverage_empty_catalog_and_nothing_loaded_is_full` — empty `job_catalog.JOBS` fixture, empty `loaded` → `fraction == 1.0` (vacuous, matches today's `if discovered else 1.0` edge case).
11. `test_coverage_empty_catalog_with_loaded_jobs_is_zero_covered` — empty catalog, one loaded job → `covered == 0`, that job is `unmonitored`.
12. `test_coverage_survives_loaded_here_raising` (dependency failing: `launchctl` missing/throws) — `coverage()` never crashes `run_all`; treats it as "no local jobs known," not a sweep-ending exception.
13. `test_plist_label_to_job_name_strips_known_prefixes` and the two `check_cron_job_log` tests — **deleted** (test the deleted mechanism).

**Every result has `checked_at`**
14. `test_guarded_backfills_checked_at_when_missing` — a check returning a dict with no `checked_at` gets one stamped at collection time.
15. `test_guarded_preserves_existing_checked_at` — a check that already stamps its own `checked_at` (e.g. a cross-machine probe's own clock) is not overwritten.

**Repeats/concurrency**
16. `test_coverage_is_pure_no_shared_state_across_calls` — two sequential calls with different fixtures don't leak state (catches an accidental module-level cache).

**`contract:*`/`purpose:missed` amber-not-red** (narrative "Fix:", not boxed, but required by "What to build")
17. `lib/tests/test_output_contracts.py`: update the two tests currently asserting `severity == "red"` (never-consumed, consumed >30 days ago) to assert `"yellow"`.
18. `lib/tests/test_purpose_metrics.py`: update the test asserting `found[0]["severity"] == "red"` to assert `"yellow"`.
19. New: `test_output_contracts_never_emits_red` / `test_purpose_metrics_health_findings_never_emits_red` — a parametrized sweep over all current branches confirms neither function can return `"red"` any more (locks in the "cap at yellow" contract so a future edit can't silently reintroduce it).

## Decisions

<!-- marvin:decisions -->
### contract-red-escalation: How should `contract:*` / `purpose:missed` ever reach red, if at all?
- [ ] A: Never — cap both at yellow unconditionally. A real blocking consequence always has its own independently-red check elsewhere in the sweep (`pipeline:breaker`, `main:green`, etc.), so no new "does this block something else" detector is needed.
- [ ] B: Keep today's one red path — a contract unconsumed past the existing 30-day cut (`CUT_AFTER_DAYS`) stays red as a "removal candidate," since that already reads as a real, distinct decision rather than an ordinary missed purpose.
- [ ] C: Something else (text)

## Task List

1. `lib/health_checks.py`: delete `check_cron_job_log`, `_cron_job_logs`, `discover_launchd_jobs`, `_plist_label_to_job_name`, the `("cron", "Cron job logs", _cron_job_logs, CHECK_BUDGET_S)` entry in `default_checks()`, and the now-unused `import cron_health as ch`. Leave `cron_health.py` itself untouched (still feeds `cron-health.md` for the session-start hook).
2. `lib/health_checks.py`: rewrite `coverage()` to take a `loaded` mapping (default `job_catalog._loaded_here()`, wrapped so a `launchctl` failure degrades to "no local jobs known" instead of raising); denominator/numerator derived from `job_catalog.JOBS` (reusing the same `com.marvin.*`/`machine != "none"` filter already used for `JOB_PLACEMENT`, factored out once); `unmonitored_jobs` = loaded-but-not-catalogued only. Update the call site in `run_all()`.
3. `lib/health_checks.py`: in `guarded()`, after validating each row is well-formed, backfill `checked_at` with the collection timestamp for any row that doesn't already carry one.
4. `lib/machine_profile.py`: add `is_calibrated(device_id)` reading the registry's `calibrated` field (default `True`; only an explicit boolean `false` disables it; fails open on an unreadable registry, matching `_load_registry()`).
5. `lib/health_checks.py`: in `run_all()`, after collecting all results and before `coverage()`/`overall_severity()`, fold every result whose id names an uncalibrated device (`machine:<dev>`, anything ending `@<dev>`, or `sync:stuck:<dev>:...`) into one row per device, severity a new neutral constant (`UNCALIBRATED`), detail "not reporting yet — awaiting calibration before it counts toward the verdict."
6. `dashboard/src/components/HealthDashboard.jsx`: add one `SEVERITY_COLOR.uncalibrated` entry (grey/neutral, parallel to `unmonitored`). No other dashboard change needed — `stalenessOpacity`'s staleness fix and the overall-verdict exclusion both fall out of steps 3 and 5 with zero further UI code.
7. `lib/output_contracts.py` / `lib/purpose_metrics.py`: apply the Decision above (expected: change the red branch(es) to yellow).
8. Update/add tests per the list above in `lib/tests/test_health_checks.py`, `lib/tests/test_machine_profile.py`, `lib/tests/test_output_contracts.py`, `lib/tests/test_purpose_metrics.py`.
9. Run the full Python suite (not just the touched files) before opening the PR, per the merge gate's "tests try to break it" requirement.
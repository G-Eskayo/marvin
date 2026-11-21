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
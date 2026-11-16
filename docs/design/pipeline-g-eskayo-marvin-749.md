## North-star fit

**Reuses before adding anything new:**
- `evidence_capture.capture_ios_simulator`/`capture_macos_app` (`lib/evidence_capture.py:330-444`), wired in through `project_profile.Measurer.evidence()` (`lib/project_profile.py:534-561`), is the real, dispatched capture path for clarity-captions and marvin-voice — not `lib/simulator_capture.py`. That module (and its all-`pass` test file `lib/tests/test_simulator_capture.py`) is dead scaffolding from an unrelated ticket (marvin#126, see `docs/design/pipeline-g-eskayo-marvin-126.md`), never imported by `project_profile.py` or `run_ticket.py`. The ticket's "What to build" names `lib/simulator_capture.py`; that's stale — **I'm correcting it** to target `evidence_capture.py`.
- `cleanup_sweep.sweep_simulators`/`decide_simulator` (`lib/cleanup_sweep.py:600-649`) already classifies devices into stock/capture/ticket-named and already prunes capture sims when idle. I extend this one function (new branch + widened `lastBootedAt`/`dataPath` fields on `_default_list_simulators`) instead of writing a parallel pruning module, and call the same `sweep_simulators()` from the capture entrypoint at run start, not just from the daily cron.
- Disk accounting for the new shared Swift cache reuses `disk_ledger.measure_categories`'s existing `rebuildable_caches` walk of `~/Library/Caches` (`lib/disk_ledger.py:143`) — putting the cache at `~/Library/Caches/marvin/swift-packages` means zero changes to `disk_ledger.py`/`disk_categories.py`.
- The Recurrence-check probe reuses the `purpose_metrics.PROBES` registry pattern (`lib/purpose_metrics.py:442-475`) and the already-running daily `disk_ledger.run_daily_ledger()` samples (`lib/disk_ledger.py:249`), rather than inventing new logging. The 15 GB threshold is read from `config/dispatch.json`'s existing `guards.min_disk_gb`, never re-hardcoded.
- `node_modules_seed.py` (#687) is the nearest *analogous* pattern (shared-cache-across-worktrees) but is the wrong shape to copy: it exists because npm has no native shared-cache flag. Swift's own `-clonedSourcePackagesDirPath` / `--cache-path` give the same effect natively, with Apple's own locking — no copy-on-write/atomic-rename machinery needs to be built.

**Simplest sufficient approach:** inject the shared-cache flag in the two places the *engine itself* constructs Swift/xcodebuild argv (`evidence_capture._capture_ios`/`_capture_macos`, `project_profile.Measurer`'s `swift build`/`swift test` tiers) so every current and future Swift project profile gets the fix for free, with zero per-project JSON edits. Only one inline shell command (clarity-captions' `spike-app` tier, a `bash -c` string) can't be auto-rewritten safely; that one needs a single-line edit using an env var the engine now exports.

**Where it saves/spends tokens:** spends a small, bounded amount of new engine code (one flag-injection point, one `decide_simulator` branch, one probe function) to stop a recurring disk incident that otherwise costs manual du/cleanup time and blocked dispatch (`guards.min_disk_gb`) each time it recurs. No new module, no new daemon.

**Phone-OS direction:** indirectly — keeps the Mini (a MARVIN compute node) usable rather than wedged by disk pressure; not itself an OS-shaped feature.

**More capable, not more passive:** yes — the owner stops needing to do by-hand du/find audits and manual cleanup (as he did 2026-10-28); the pipeline now states its own disk complexity claim with real numbers instead of someone discovering the problem again.

**Correcting the ticket's own scope (a defect worth naming, not working around):** `config/projects/*.json` lives in the **private instance repo** (ADR 0071 — "public engine, private instance"), not in `G-Eskayo/marvin`. `clarity-captions`' and `marvin-voice`'s own build scripts live in those **separate GitHub repos**, which this worktree (and any ticket executor scoped to `G-Eskayo/marvin`) has no write access to. The ticket's "What to build" asks a single marvin PR to touch all three. That's very likely why the prior attempt failed code review three times without a reusable fix. This plan ships what's actually deliverable from a `G-Eskayo/marvin` PR, applies the (ungated, non-PR) instance-repo profile edit directly per ADR 0071/0021, and files separate tickets for the two app-repo pieces instead of pretending to edit files this PR can't reach.

## Tests to write first

From the ticket's "How we'll try to break it":

1. **Concurrent cache writers, no corruption.** Two concurrent calls to the new shared-cache-dir helper (`ensure_shared_cache_dir`-style `mkdir(parents=True, exist_ok=True)`) from threads never raise and leave exactly one directory (mirrors `node_modules_seed`'s `test_concurrent_stores_leave_exactly_one_complete_entry` style, but for a plain idempotent mkdir — no custom locking, since Apple's tools own package-level atomicity).
2. **Cache folder missing/deleted mid-run.** The command-building helper that injects `-clonedSourcePackagesDirPath`/`--cache-path` recreates the directory before each run even if it was removed between calls; a build command's argv/env is correct regardless of whether the directory pre-exists.
3. **Simulator in use when pruning runs: kept.** `decide_simulator` given a MARVIN-reused device, idle 20+ days, `state == "Booted"` → `"keep"`.
4. **Hand-made/Xcode device: never deleted.** `decide_simulator` given a non-`marvin-`-prefixed device idle 100+ days → `"keep"`/`"review"`, never `"remove"`.
5. **Cleanup run twice is a no-op.** `sweep_simulators()` run twice against the same fixture list: second run's `removed` is empty (nothing left to remove).
6. **No new device when a named one exists.** The create-if-missing helper, given a device list that already contains the target name, makes no `simctl create` call.
7. **Device missing → created once, reused after.** First call creates it (`simctl create`); a second call with the device now present makes no second create call.

Bad/empty/huge/malformed input:

8. Device-name/cache-path strings sanitized the same way `validate_scenario` already sanitizes `screen` (no path traversal, no null bytes, bounded length) before they reach `simctl`/`xcodebuild` argv.
9. `xcrun simctl list devices --json` returns truncated/non-JSON output → treated as "nothing to prune," never crashes (matches existing `_simctl_json`'s `{}` fallback).
10. A device with no `lastBootedAt` (never booted since creation) → not treated as instantly 14-days-overdue; falls back to the device's `dataPath` folder mtime, and if that's also unavailable, kept (never guessed into deletion).

Each dependency failing:

11. `xcrun`/`simctl` entirely missing (mac-mini-2012) → create-if-missing and prune both no-op cleanly (reuses `shutil.which("xcrun") is None` guard already in `sweep_simulators`).
12. `simctl create` fails (bad device-type/runtime on this machine) → raises `EnvMissing`-shaped error (machine can't do this; not counted as the ticket's fault), mirroring `SimulatorUnavailable`.
13. A `swift build --cache-path`/`xcodebuild -clonedSourcePackagesDirPath` run that fails for an unrelated real reason still reports `build_ok: 0`/parsed failure exactly as before the change (non-regression: our injection never swallows a real failure).

Repeats and concurrency:

14. Two concurrent `decide_simulator`/`sweep_simulators()` calls (daily cron + a capture run starting at the same moment) never double-delete or crash on an already-gone UDID (reuses existing `"review: simctl refused to delete it"` path).
15. The new `_default_list_simulators` field additions (`lastBootedAt`, `dataPath`) don't change behavior for the *existing* stock/ticket-named/old-capture-sim branches — explicit non-regression test against today's `test_cleanup_sweep.py` fixtures.

Wrong permissions/machine:

16. Running on a Linux/no-Xcode machine → every new function no-ops (shared with #11).
17. Shared cache directory not writable → the build fails with a clear error; our wrapper doesn't mask it as a false pass.

Stale state:

18. A MARVIN-reused device whose name no longer matches any current profile (profile renamed/removed) is still prunable by the generic prefix+age rule — no profile-specific coupling required.

A person's mistakes:

19. A hand-made device that happens to start with `marvin-` by coincidence: documented, accepted limitation (same trust boundary the existing `CAPTURE_SIM_RE` scheme already relies on) — covered by a Decision below rather than silently engineered around.

Recurrence-check probe:

20. New `purpose_metrics` probe counting days under `config/dispatch.json`'s `guards.min_disk_gb`, from crafted `disk-ledger.jsonl` fixtures: correct day-count over the window; a day with **no** ledger entry (machine was off) is excluded, never silently assumed under or over.

**Verify fails when code changes without a test changing:** each new/changed function above (`ensure_shared_cache_dir`, the `Measurer` command-rewrite for `swift build`/`swift test`, `_capture_ios`/`_capture_macos`'s new create-if-missing + flag injection, `decide_simulator`'s new branch, `_default_list_simulators`'s new fields, the new probe) gets at least one test whose assertion breaks if that function's behavior changes.

## Decisions
<!-- marvin:decisions -->
### sim-name: Reused screenshot-capture simulator — keep Xcode's stock device name, or switch to a MARVIN-owned, create-if-missing device?
- [ ] A: Keep using the profile's current stock device name (e.g. "iPhone 17 Pro"). Simpler, zero new simulator appears on the owner's Mac, but has no defense if that stock device is ever deleted by hand or by a future cleanup change.
- [ ] B: Switch to a MARVIN-owned name (e.g. `marvin-cap-clarity-captions`), created once if missing and pruned by the new 14-day-unused rule. Matches the acceptance criterion's literal "devices created by MARVIN" framing; adds one simulator to the owner's device list per project.

### orphan-module: lib/simulator_capture.py (dead scaffolding from marvin#126, never wired in)
- [ ] A: Delete it and its all-stub test file now, as part of this PR (it adds confusion, as this ticket's own mistriage shows).
- [ ] B: Leave it; file a separate small ticket to either finish wiring it up or delete it later.

### hand-made-marvin-prefix: A person-made simulator that happens to start with "marvin-" (unlikely, but possible)
- [ ] A: Accept the risk, same trust boundary the existing `CAPTURE_SIM_RE` scheme already lives with — no extra defense.
- [ ] B: Add a lightweight marker (e.g. a sentinel file in the device's data folder) so only devices MARVIN itself created are ever eligible for pruning, at the cost of a bit more code.

## Task List

1. **`lib/evidence_capture.py`** — add a `SWIFT_PACKAGE_CACHE` constant (`~/Library/Caches/marvin/swift-packages`), a small `ensure_shared_cache_dir()` helper (idempotent `mkdir(parents=True, exist_ok=True)`), and inject `-clonedSourcePackagesDirPath <dir>` into `_capture_ios`'s and `_capture_macos`'s `xcodebuild ... build` argv (lines ~349-351, ~413-415).
2. **`lib/project_profile.py`** — export `MARVIN_SWIFT_PACKAGE_CACHE` in `build_env()`, and in `Measurer` (or `with_required_checks`) transparently append `--cache-path <dir>` to any verify/setup command whose argv starts with `["swift", "build"]`/`["swift", "test"]`, reusing `ensure_shared_cache_dir()` before each run.
3. **`lib/evidence_capture.py`** — add `ensure_simulator(name, device_type, runtime=None)`: create-if-missing via `simctl create`, idempotent, raises an `EnvMissing`-style error on failure; wire it into `_capture_ios` before the existing `boot` call.
4. **`lib/cleanup_sweep.py`** — widen `_default_list_simulators()` to also surface `lastBootedAt` and `dataPath`; add a new branch to `decide_simulator()` for MARVIN-reused (prefix-matched, per the `sim-name` decision) devices: kept while booted or used within 14 days, removed otherwise; non-regression for the existing stock/ticket-named/old-capture-sim branches.
5. **Wire pruning to run start** — call `cleanup_sweep.sweep_simulators()` at the top of `evidence_capture.capture_ios_simulator`/`capture_macos_app`, not only from the daily cron.
6. **`lib/purpose_metrics.py`** — add a new probe (e.g. `"mini-disk-under-floor"`) counting days, over the probe window, where `disk-ledger.jsonl`'s `free_kb` (device = the Mini) was under `config/dispatch.json`'s `guards.min_disk_gb`; register it in `PROBES`. Fill in the ticket's `## Recurrence check` with this probe's name.
7. **Direct instance-repo edit (ADR 0071/0021, no PR gate)** — `~/.agents/instance/config/projects/clarity-captions.json`: point the `spike-app` tier's inline `xcodebuild` call at `-clonedSourcePackagesDirPath "$MARVIN_SWIFT_PACKAGE_CACHE"`; apply the `sim-name` decision to `evidence.dev.ios_simulator.simulator` once answered.
8. **Tests** — add the 20 cases above to `lib/tests/test_evidence_capture.py`, `lib/tests/test_project_profile.py`, `lib/tests/test_cleanup_sweep.py`, `lib/tests/test_purpose_metrics.py`.
9. **Apply the `orphan-module` decision** — delete `lib/simulator_capture.py` + `lib/tests/test_simulator_capture.py`, or file the separate cleanup ticket.
10. **File a follow-up ticket against `G-Eskayo/marvin-voice`** for AC2 (`scripts/install.sh` removing its `.build/xcode` folder on success, keeping it on failure) — out of reach from this repo.
11. **`CONTEXT.md`** — update "Per-project execution profiles" to document the automatic shared-cache injection, so future profile authors know they get it for free and don't need per-project flags.
12. **Measure and record** before/after shared-cache size (reusing `cleanup_sweep._tree_bytes`) and simulator count in the PR body, and state the O(open PRs × one build) claim with those numbers, per AC4.
## North-star fit

**Reuses:** `lib/evidence_capture.py::_with_build_folder`/`_capture_ios`/`_capture_macos` — the one choke point where every UI-touching ticket for clarity-captions, marvin-mobile, nourished and killer-sudoku already builds with a disposable, per-run `xcodebuild -derivedDataPath <mktemp>` (added 2026-10-27 to stop DerivedData itself piling up). It never points `-clonedSourcePackagesDirPath` anywhere, so each of those disposable builds re-resolves every Swift package from scratch — this is the actual mechanism behind "FluidAudio x5," not `lib/simulator_capture.py` (see correction below). One change here fixes the duplicate-download problem for every project that uses evidence capture, not just clarity-captions — compounding leverage, north star 4. Also reuses `lib/disk_trim.py::_trim_swiftpm` (already deletes `~/Library/Caches/SwiftPM` under disk pressure, ADR 0056/0065 "costly" tier) by making that the literal shared-cache path, so the new cache gets ADR-0065-correct auto-trim for free — no new trimming code. For simulators, reuses `lib/cleanup_sweep.py::decide_simulator`'s existing `CAPTURE_SIM_RE` branch (already the live, scheduled mechanism) rather than the unused `lib/simulator_capture.py` module (see correction). For `install.sh`, reuses its own existing `set -euo pipefail` early-exit as the "kept on failure" guarantee — the cleanup line only needs adding at the end.

**Correction to the ticket's "What to build":** `lib/simulator_capture.py::capture_scenarios` has **zero production callers** (`grep` confirms it's referenced only by its own, partly-stubbed test file and a design doc, docs/design/pipeline-g-eskayo-marvin-126.md). The live screenshot path, wired per CONTEXT.md and the `ios-app` playbook, is `lib/evidence_capture.py::capture_ios_simulator`/`capture_macos_app`, which reuses a profile-named **stock** Apple simulator (`"iPhone 17 Pro"`) and creates nothing new — `cleanup_sweep.sweep_simulators`'s stock-name check already protects it, so "create no new device when a named one exists" is already true there. Also, for clarity-captions, the profile's own `verify.spike-app.command` text (`config/projects/clarity-captions.json`) is **dead**: `project_profile.with_required_checks` overrides it with `.github/required-checks.json`'s command whenever that file exists (it does, for clarity-captions). The real xcodebuild invocation to fix for clarity-captions' build/CI gate is in `.github/required-checks.json`, not the profile JSON. I flag the simulator-file choice as a Decision below since it changes which module carries the fix.

**Simplest sufficient approach:** one canonical shared path (`~/Library/Caches/SwiftPM`, matching `disk_trim._trim_swiftpm`'s existing hardcoded path) passed as `-clonedSourcePackagesDirPath` everywhere an `xcodebuild` build happens; no new env-var convention, no new trimming code, no new cross-repo dependency (marvin-voice and clarity-captions stay self-contained — literal path, not a call into `~/.agents`, matching their existing standalone-script style).

**Tokens/compute:** saves real wall-clock and network/disk on every Mini build (fewer FluidAudio re-downloads); the planning pass itself spent most of its budget on cross-repo investigation (confirming which code path is actually live) rather than guessing from the ticket text.

**Capability:** this is pure infra/disk hygiene — it leaves Gil more capable only indirectly (fewer disk-floor refusals blocking ticket merges); no UI, no behavior change for him to learn.

**Cross-repo scope:** this ticket's fix spans four separate git repos. This worktree is `G-Eskayo/marvin` (engine) only:

| Repo | Files | Why |
|---|---|---|
| `G-Eskayo/marvin` (this worktree) | `lib/evidence_capture.py`, `lib/disk_trim.py`, `lib/cleanup_sweep.py`, their tests | the live build/evidence/cleanup code |
| `G-Eskayo/marvin-instance` (private, separate clone at `~/.agents/instance`) | `config/projects/clarity-captions.json` (cosmetic only — see above) | profile JSON, not versioned in this repo despite CONTEXT.md's stale line 1161 |
| `G-Eskayo/clarity-captions` | `.github/required-checks.json` | the actual CI/gate build command |
| `G-Eskayo/marvin-voice` (private) | `scripts/install.sh` | the actual local-install build command |

Only the first can be delivered as a PR from this worktree. The other three need their own PRs in their own repos/worktrees — I list them in the task list but cannot open them from here.

## Decisions

<!-- marvin:decisions -->
### sim-file: Where should the 14-day simulator-prune rule live?
- [ ] A: In `lib/cleanup_sweep.py`'s existing `decide_simulator`/`sweep_simulators` (the mechanism that actually runs nightly today), adding a last-used-day check to its existing `CAPTURE_SIM_RE` branch. No new caller needed; fixes the problem where it actually occurs.
- [ ] B: In `lib/simulator_capture.py` as the ticket literally names, even though that module has no production caller today — the fix would sit dormant until something wires `capture_scenarios` in (a separate, unscoped piece of work).
- [ ] C: Both — A now, and also update `lib/simulator_capture.py` so it's correct if/when ADR 0052 parallel dispatch wires it in later.

### release-script-cache: Should `clarity-captions/scripts/release-mac.sh`'s archive build also get the shared `-clonedSourcePackagesDirPath`?
- [ ] A: Yes, for consistency — it's an `xcodebuild archive` that resolves the same packages.
- [ ] B: No — it's a rare, manual, one-off release build on the shared checkout (not a per-worktree ticket build), not part of the disk problem this ticket measures; leave it out to keep the PR scoped.

## Tests written first

One per "How we'll try to break it" bullet, plus the ticket's general misuse categories:

1. **Two builds back to back share one copy on disk** — `lib/tests/test_ios_evidence.py` / `test_macos_evidence.py`: fake `run` records argv; assert both `_capture_ios` and `_capture_macos` pass the same `-clonedSourcePackagesDirPath <shared>` on two successive calls, and (new) a disk-measurement test using a real tiny local git repo as a fake "package" that two sequential disposable-DerivedData builds resolve into the same shared folder — assert the folder holds exactly one checkout after both runs.
2. **Concurrent resolution into the shared cache doesn't corrupt** — integration-style test (skipped if `xcrun`/`swift` unavailable, same skip pattern as the MLX adapter tests per `2b3f7b1c`): two real `xcodebuild`/`swift build` processes against a tiny fixture package, pointed at the same shared folder at the same time; assert both succeed and the checkout is valid afterward.
3. **Shared folder deleted mid-run** — test that passes a `-clonedSourcePackagesDirPath` to a path that doesn't exist (simulating it being trimmed away) and asserts the build still succeeds (mkdir -p before invocation, verified by argv/call-order assertion, not a dangling-path failure).
4. **install.sh: success removes `.build/xcode`, failure keeps it** — a bats/shell test (or a Python subprocess test) that runs `install.sh` with a mocked/failing `xcodebuild` (nonzero exit) and asserts `.build/xcode` survives; then a successful run and asserts it's gone.
5. **A booted CAPTURE_SIM_RE device is never pruned** — extend `lib/tests/test_cleanup_sweep.py::test_a_leftover_capture_simulator_is_removed_once_it_is_shut_down`: booted stays kept regardless of last-used age.
6. **Devices created by MARVIN, unused 14+ days, are deleted; freshly-used ones are not** — new test driving `decide_simulator`/`sweep_simulators` with an injected `last_used` callable (mirrors the existing DI style, e.g. `ticket_open`), one case at 13 days (kept) and one at 15 days (removed).
7. **Running simulator pruning twice is a no-op the second time** — call `sweep_simulators` twice with the same fixture state; second call's `removed` list is empty.
8. **Xcode's own stock device, and an unrecognized hand-made name, are never touched** by the new time-based rule — regression test alongside existing `test_a_simulator_the_sweep_cannot_tie_to_a_ticket_is_reported_not_deleted`.
9. **Running `install.sh` twice in a row** never accumulates two `.build/xcode` folders (each run cleans its own).
10. **Shared cache path exists but is unwritable (permissions)** — build degrades gracefully: omits `-clonedSourcePackagesDirPath` and still succeeds (per ADR 0065's "cleanup never blocks the real work"), logged, not silently masked and not a hard failure.
11. **`disk_trim._trim_swiftpm` still trims exactly the path the builds now write into** — a test asserting the constant is shared (import, not a duplicated literal), so the two can't drift.
12. **Stale `Package.resolved` in the shared cache** — changing a dependency version with a pre-populated shared cache still builds the new version, not the cached old one (trusts SwiftPM's own update-in-place; test guards the interaction, not reinvents it).

## Task List

1. **marvin engine (this repo/worktree):**
   - [ ] Add `disk_trim.SWIFTPM_SHARED_CACHE_DIR = HOME / "Library" / "Caches" / "SwiftPM"`; point `_trim_swiftpm` at it (same path, now named).
   - [ ] `lib/evidence_capture.py`: in `_capture_ios` and `_capture_macos`'s xcodebuild calls, `mkdir -p` the shared dir and add `-clonedSourcePackagesDirPath <disk_trim.SWIFTPM_SHARED_CACHE_DIR>`; degrade (omit the flag, log) if the dir can't be created/written.
   - [ ] Write tests 1, 3, 10, 11, 12 against `lib/tests/test_ios_evidence.py` / `test_macos_evidence.py`.
   - [ ] (Per Decision `sim-file`) extend `lib/cleanup_sweep.py::decide_simulator`/`sweep_simulators` with an injectable `last_used` lookup (default: the simulator's `dataPath` folder mtime) and a 14-day threshold for the `CAPTURE_SIM_RE` branch only; extend `_default_list_simulators` to carry `data_path`.
   - [ ] Write tests 5, 6, 7, 8 against `lib/tests/test_cleanup_sweep.py`.
   - [ ] Add test 2 (concurrency), skipped when Xcode/swift tooling is missing.
   - [ ] Update CONTEXT.md's stale line ("`config/projects/<repo>.json`, versioned in this repo") to say it lives in the private instance repo (ADR 0071), since I'm touching this area and found the drift.
   - [ ] State disk use as O(open PRs × one build) in the PR, with before/after sizes for the shared cache and the simulator count, measured on the Mini.
   - [ ] Add the probe: a counter of days the Mini's free space fell under the pipeline's 15 GB floor, read from `disk_triggers.LOG_PATH`, checkable on 2026-11-30.

2. **`G-Eskayo/marvin-voice` (separate repo, separate PR):**
   - [ ] `scripts/install.sh`: add `-clonedSourcePackagesDirPath "$HOME/Library/Caches/SwiftPM"` (with `mkdir -p` first) to the `xcodebuild ... build` call; add `rm -rf "$root/.build/xcode"` after `codesign --verify --strict` succeeds (before the diagnostic echo/open), so failure (caught by `set -euo pipefail`) always keeps the folder.
   - [ ] Write test 4 and 9 (a shell-level test harness or a Python subprocess-driven test, matching whatever test style already exists in that repo).

3. **`G-Eskayo/clarity-captions` (separate repo, separate PR):**
   - [ ] `.github/required-checks.json`: add `mkdir -p "$HOME/Library/Caches/SwiftPM"` and `-clonedSourcePackagesDirPath "$HOME/Library/Caches/SwiftPM"` to the `spike-app` and `mac-app` check commands.
   - [ ] Per Decision `release-script-cache`, optionally do the same in `scripts/release-mac.sh`'s archive build.
   - [ ] Confirm `node --test scripts/required-checks.test.mjs` (the drift test) still passes after the command string changes.

4. **`G-Eskayo/marvin-instance` (private repo, separate PR):**
   - [ ] Update `config/projects/clarity-captions.json`'s `verify.spike-app.command` text to match `.github/required-checks.json` for documentation accuracy, with a one-line note that it's currently superseded by `with_required_checks`. No change needed to `marvin-voice.json` (its only verify tier is `swift test`, not `xcodebuild`, so it's unaffected by this ticket).
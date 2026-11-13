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
## North-star fit

**Reuses before adding anything new:**
- `lib/evidence_capture.py:capture_ios_simulator`/`_capture_ios` (screenshot loop, `-derivedDataPath` build-folder cleanup via `_with_build_folder`, `_run_checked` error formatting) — the recording capture reuses the same build/boot/appearance-loop scaffold, adding a recording step per declared scene rather than inventing a parallel pipeline.
- `lib/project_profile.py:Measurer.evidence()`'s existing try/except contract (`capture failed: {e}` reported in the PR, never raised) — extended, not replaced, for recording failures.
- `docs/design/merge-animation-757/record.mjs`'s two-pass ffmpeg palette GIF filter (`palettegen`/`paletteuse`) — reused verbatim as the GIF-encode step for both the iOS recordings and the dashboard recording, instead of inventing a second GIF technique.
- `dashboard/src/lib/cdp_capture.js:captureViaCdp`'s Electron-attach/CDP/cleanup scaffold — reused for the dashboard recording rather than a second Electron-launch path.
- `dashboard/webhook-server/ui_evidence.js`'s existing `DEFAULT_UI_PATTERNS`/`glob_to_regex`/profile-override mechanism (also mirrored in `evidence_capture.py:ui_files`) — reused as the template for the new motion-path list, rather than a new classifier.
- `mr_raiser.py:_format_code_review`'s "Notes (not blocking)" convention — reused for the animation-diff-but-stills-only warning, instead of inventing a new non-blocking-signal mechanism.
- **Already built, not touched:** the dashboard PR-detail gallery (`dashboard/src/components/PrImages.jsx`, `dashboard/electron/main/pr_images.js`) already renders GIFs (as `<img>`, they animate natively) and plays MP4/MOV/WEBM inline (`kind: 'video'`, `<video autoPlay loop muted>`), with its own size caps (`maxVideoBytes = 100 MB` display-side) and media cache. The ticket's "dashboard PR detail renders them... in progress in the same session" line is **done** — confirmed by reading the code, not assumed. This plan only adds the *capture* side.

**Simplest sufficient approach:** no new capture architecture. iOS gets one more step (`recordVideo` + SIGINT-stop + ffmpeg GIF/MP4) bolted onto the existing per-scene loop; the dashboard gets a duration-sampled variant of the existing single-screenshot CDP capture (no new scripted-interaction DSL — recording "whatever's already animating for N seconds" captures the stated need — "animations, transitions, the pause/save flow" — without building a click-sequence engine nothing in the ticket actually asks for).

**Where it spends/saves:** spends disk/git-history bytes per UI PR (bounded by the ticket's own caps — GIF ≤ 8 MB, MP4 ≤ 50 MB — which is the owner's answer to that cost, not a new one to solve). Spends no new GitHub API calls on the gate side (`hasImage` extension is a pure regex change, no network). Zero new runtime dependencies beyond `ffmpeg`, already used by `record.mjs` on the Mini.

**Phone-OS / capability fit:** more capable, not more passive — closes a real blind spot the owner named directly ("I want it to show functionality... if it is visual"); he currently has to run the simulator himself to see motion. This is squarely what north star 3 asks for: the owner approves from evidence he can actually see, without doing the work himself.

**Which machine:** Mac Mini (`mac-mini-1`) — it's the only machine with the iOS simulator and Xcode toolchain (per `config/playbooks/ios-app.json`'s existing `machine` assignments for `app-build`/`look-proof`), and ffmpeg is already installed there for `record.mjs`.

## Files read
`docs/adr/0024-fixed-pr-evidence-schema-adaptive-later.md`, `lib/evidence_capture.py` (full), `lib/simulator_capture.py` (full — confirmed **dead code**, superseded by `evidence_capture.py`; not imported anywhere outside its own test), `lib/project_profile.py` (`Measurer.evidence`, `playbook_notes`, `have`), `lib/mr_raiser.py` (`_format_dev_evidence`, `_format_code_review`, `_default_open_pr`), `dashboard/webhook-server/ui_evidence.js` (full), `dashboard/src/lib/file_kinds.js` + `dashboard/electron/main/pr_images.js` (full — confirmed the gallery/video rendering is already built), `dashboard/src/components/PrImages.jsx` (full), `dashboard/src/lib/cdp_capture.js`, `dashboard/scripts/capture_screenshot.mjs`, `docs/design/merge-animation-757/record.mjs` (full), `config/playbooks/ios-app.json`/`.md`, `lib/tests/test_ios_evidence.py`, `lib/tests/test_macos_evidence.py`, `docs/agents/decisions-format.md`, CONTEXT.md (PR-state/evidence sections), issue #374 (blocker, closed) and its own text. No PR or branch exists for any prior attempt at #379 — `git log --all --grep=379`, `git diff main...HEAD` (empty), `gh pr list --search 379` all confirm the three failed runs left no code; the two issue comments give only "max_iterations" / "must-fix issues" with no specifics.

## Decisions

<!-- marvin:decisions -->
### schema: Where does a recording scene live in the profile?
- [ ] A: `evidence.dev.ios_simulator.recordings: [{scene, seconds}]` — nested under the existing `ios_simulator` block, `scene` referencing a name already declared in that block's `scenes` list (reuses the existing light/dark appearance loop for free; no new top-level evidence key)
- [ ] B: `evidence.recordings: [{scene, seconds}]` exactly as written in the ticket's example — a sibling of `dev`, applying across whichever capture kind is configured

### dashboard-video-scope: How much of "Playwright video for the dashboard" ships in this PR?
- [ ] A: Minimal — record N seconds of whatever's already on screen after load (periodic `page.screenshot()` sampling via the existing `captureViaCdp` attach, ffmpeg-assembled), no scripted interaction sequence. Covers self-playing motion (spinners, transitions, the pause/save flow) but not a multi-step click-through.
- [ ] B: Full scripted capture — profile declares a sequence of clicks/waits to drive the recording, in this PR
- [ ] C: Defer the dashboard/Electron half to its own follow-up ticket; ship iOS recording (which is what every acceptance criterion and break-it case in #379 actually tests) now

### oversize: A scene's GIF or MP4 comes out over its cap (8 MB / 50 MB) after ffmpeg encodes it
- [ ] A: Report it as a per-scene capture failure (same "capture failed: ..." pattern already used for a crashed build), drop that file, keep whatever else succeeded
- [ ] B: Re-encode once at a lower resolution/bitrate to try to fit the cap before giving up

## Tests (write first)

**`lib/tests/test_ios_evidence.py`** (extends the existing `CFG`/`FakeRun` fixtures) — one test per break-it case plus misuse:
1. `test_recordvideo_is_started_and_stopped_with_sigint_per_scene` — a configured recording scene starts `xcrun simctl io booted recordVideo <path>.mp4` via `Popen`, is sent `SIGINT` after `seconds`, and the resulting file is accepted only once it looks like a real MP4 (reuse the ftyp-magic check style already used for PNG in `_capture_macos`).
2. `test_each_recorded_scene_becomes_a_gif_and_an_mp4` — ffmpeg's two-pass palette conversion runs and both paths come back in the scene's result dict.
3. `test_a_scene_crashing_mid_recording_does_not_lose_the_others` — `FakeRun`/fake `Popen` simulates the app terminating mid-recording (recordVideo process exits early / writes a zero-byte file); that scene is reported with `ok: False` and a reason, the remaining scenes in the batch still capture.
4. `test_recording_never_stops_is_killed_after_a_timeout` — the recordVideo process ignores SIGINT; after a bounded wait it is SIGKILLed and reported as a failure, never hangs the pipeline.
5. `test_ffmpeg_missing_is_reported_not_raised` — `shutil.which("ffmpeg")` returns `None`; each affected scene is reported `ok: False` with a plain "ffmpeg not found" reason, screenshots for the same ticket still succeed.
6. `test_simulator_already_recording_is_reported_not_crashed` — simctl's real "already recording" stderr on a second concurrent recordVideo call against the same booted device is caught and reported per-scene, not raised, mirroring the existing `test_an_already_booted_simulator_is_fine` tolerance for boot.
7. `test_a_recording_scene_name_not_declared_in_scenes_is_refused_plainly` — `recordings: [{"scene": "typo", "seconds": 5}]` with no matching `scenes` entry raises `ValueError` up front, before anything runs.
8. `test_seconds_is_validated` — zero, negative, non-numeric, and an unreasonably huge value (e.g. 999999) are all rejected with `ValueError` before any subprocess runs.
9. `test_output_over_its_size_cap_is_reported_as_a_capture_failure` (per Decision `oversize`=A) — a fake ffmpeg output larger than `GIF_MAX_BYTES`/`MP4_MAX_BYTES` is dropped and reported, not committed.
10. `test_measurer_merges_screenshot_and_recording_results` — `Measurer.evidence()` returns both `screenshots` and `recordings` in `dev_evidence` for a UI-touching ticket whose profile configures both.
11. `test_the_pr_body_links_the_gif_and_the_mp4_pinned_to_the_commit` (in `mr_raiser`'s section, same file or a new one) — `_format_dev_evidence` renders `![](...gif)` and a link/`<video>` for the `.mp4`, both pinned to the head SHA like existing screenshots.
12. `test_animation_diff_with_only_stills_gets_a_non_blocking_note` — a changed file matching the new motion-path patterns, with screenshots but no GIF/video evidence, produces a "Note (not blocking): ..." line, and does **not** fail the ticket.

**`dashboard/test/ui_evidence.test.js`**:
13. `hasImage accepts a <video> tag and a bare/markdown link to .mp4/.mov/.webm as evidence` (the "stays image-or-video" requirement) — several variants, plus a bare link to a non-video file still failing (no regression of the existing "a bare link to a .png is not an image" rule).
14. `a UI PR with only a video (no <img>) is not refused NO_UI_EVIDENCE`.
15. `imagePins/unpinnedImages/imageShas still work for a <video src> pinned to a full commit SHA` (staleness/pin checks must also cover recordings, not just images).

**`dashboard/test/cdp_capture.test.js`** (or a new `recording_capture.test.js` next to it):
16. `a duration-sampled capture produces N frames at the requested interval and always cleans up the Electron process`, mirroring `captureViaCdp`'s existing cleanup tests (Electron exits mid-capture, attach timeout, etc. — reuse those existing cases for the new code path).

**Verify fails when code changes without a test changing:** every new function above (`capture_ios_recordings`/the recording branch of `_capture_ios`, the ffmpeg GIF-encode helper, the size-cap check, `ui_evidence.js`'s video-aware `hasImage`/`imageUrls`, the motion-path note in `_format_dev_evidence`, the dashboard duration-sampling capture) has at least one test above whose assertion would fail if that function's behavior changed, not a smoke test that merely runs it.

## Task List

1. Resolve Decisions `schema`, `dashboard-video-scope`, `oversize` (owner answers before/alongside implementation; this plan proceeds assuming A/A/A as the default, lowest-risk path, and the tasks below note where an answer of B/C changes scope).
2. `lib/evidence_capture.py`: add `GIF_MAX_BYTES`/`MP4_MAX_BYTES` constants, a `_mp4_to_gif(src, dest, width, run)` helper (ffmpeg two-pass palette, reused from `record.mjs`), and validation for a `recordings` list (`scene` must match a declared `scenes` entry, `seconds` bounded and numeric) inside the existing config-check at the top of `capture_ios_simulator`.
3. Add the recording step itself: start `xcrun simctl io booted recordVideo <tmp>.mp4` via `Popen` right after each scene's existing launch+screenshot, hold it for `seconds`, stop with `SIGINT` (fall back to `SIGKILL` after a bounded wait), verify the file is non-trivial, convert to GIF, enforce size caps, and catch per-scene failures so one scene's crash/missing-ffmpeg/busy-simulator doesn't drop the others' results (tests 1–9).
4. `lib/project_profile.py:Measurer.evidence()`: merge `recordings` results alongside `screenshots` into the `dev_evidence` dict returned to `mr_raiser` (test 10).
5. `lib/mr_raiser.py:_format_dev_evidence`: render each recording's GIF (`![]()`) and MP4 (`<video>` or a pinned link), both pinned to the head SHA like existing screenshots (test 11).
6. Add the motion-path check: a `DEFAULT_MOTION_PATTERNS` list + `evidence.motion_paths` profile override (mirroring `ui_paths`), and a non-blocking "Note (not blocking): ..." line in `_format_dev_evidence` when a motion-path file changed but no GIF/video evidence exists (test 12).
7. `dashboard/webhook-server/ui_evidence.js`: extend `hasImage`/`imageUrls` (and therefore `unpinnedImages`/`imagePins`/staleness checks, which all build on `imageUrls`) to recognize `<video src>` tags and markdown/bare links to `.mp4`/`.mov`/`.m4v`/`.webm`, reusing the `VIDEO_EXT` pattern already defined in `dashboard/src/lib/file_kinds.js` (tests 13–15).
8. Dashboard/Electron recording (scope per Decision `dashboard-video-scope`; skip entirely if the owner picks C): extend `cdp_capture.js` (or a new sibling module) with a duration-sampled capture mode reusing the existing attach/cleanup scaffold, assemble GIF+MP4 with the same ffmpeg helper as step 2, and wire it into `capture_dev_evidence`'s dashboard path alongside the existing single-screenshot default (test 16).
9. Run the full Python + dashboard (vitest) suites locally before committing, per the merge-gate requirement; confirm no existing `ui_evidence`/`pr_state`/`mr_review` test regressed from the `hasImage`/`imageUrls` change.
10. Open the PR against #379, with the Decisions block above so the owner's choices land as part of review rather than as a follow-up question.
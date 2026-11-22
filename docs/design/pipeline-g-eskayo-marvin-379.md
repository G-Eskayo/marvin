## North-star fit

**Reuses before adding anything:**
- `lib/evidence_capture.py::capture_ios_simulator`/`_capture_ios` (the *actually wired* path: `project_profile.py::Measurer.evidence()` → `run_ticket.py`/other-project executors → `mr_raiser.py::_format_dev_evidence`) is where recording support is added, as a sibling to the existing still-screenshot loop — not a new capture module. `lib/simulator_capture.py` claims the same integration in its docstring but is called only by its own test and a cleanup regex (`lib/cleanup_sweep.py:553`); it is dead/duplicate code, not the live path. I'm flagging this rather than quietly reviving or deleting it — out of scope for #379, worth its own small cleanup ticket.
- `docs/design/merge-animation-757/record.mjs`'s ffmpeg palette-GIF + libx264-MP4 filter graphs, and `dashboard/scripts/merge_motion_evidence.mjs::record()`'s real-time CDP `Page.startScreencast`/`screencastFrame`/`stopScreencast` → ffmpeg-concat technique, are both already proven in this repo. "Web/Electron: Playwright video for the dashboard" is built by generalizing the latter (Playwright's own `recordVideo` context option can't be used here because the dashboard is captured by `connectOverCDP` onto Electron's pre-existing context, per `dashboard/src/lib/cdp_capture.js`'s marvin#421 note — there is no "create a fresh Playwright context" step to attach `recordVideo` to).
- `dashboard/electron/main/pr_images.js` already parses `<video>`/`<source>` tags, bare `.mp4`/`.mov`/`.m4v`/`.webm` links and GitHub user-attachment video links into `kind: 'video'`, and `PrImages.jsx`/`IssueBody.jsx` already render them inline (`<video controls loop muted autoPlay>`). **Acceptance criterion 1's dashboard rendering is already built** — the issue's "in progress in the same session" note is stale; I'm correcting that against the code rather than rebuilding it.
- `lib/mr_raiser.py::_format_dev_evidence`/`_image_url` (SHA-pinned markdown formatting) and `bin/pr-shots`/`lib/pr_shots.py` (commit-and-pin) take recordings through the exact same path as screenshots — no new PR-body mechanism.
- The size-cap-with-plain-reason pattern already used in `lib/marvin_show.py` (`MAX_COPY_BYTES`, "Too big... MB; the limit is... MB") and the existing "capture failure never fails the ticket" idiom in `capture_dev_evidence`/`Measurer.evidence()` (`except (...) as e: return ..., {"na": False, "error": ...}`) are reused for size caps and recording failures respectively — no new error-handling shape.
- `project_profile.py::have()` already falls through to a generic `which(capability)` check for any unlisted name, so `ffmpeg` needs no new capability-check code.

**Simplest sufficient approach:** extend the one already-wired capture module and the one already-built dashboard gallery, rather than building a second evidence pipeline. The only genuinely new logic is (a) driving `simctl io booted recordVideo` + ffmpeg conversion + size caps, (b) generalizing the proven CDP-screencast helper into a reusable path, and (c) two gate-side gaps that are real bugs, not yet-unwritten features: `dashboard/webhook-server/ui_evidence.js::hasImage`/`imageUrls` and `lib/pr_images.py::image_urls` only recognize markdown `![]()` and `<img>` — a PR whose only evidence is a bare `.mp4` link or a `<video>` tag is **wrongly refused today** (`NO_UI_EVIDENCE`), even though `pr_images.js` (the renderer) already treats that as valid evidence. "The gate stays image-or-video" (issue text) describes intent, not current behavior; closing that gap is this ticket's job, confirmed by reading both files side by side.

**Where it spends/saves:** one-time build cost on a general capture+convert+cap helper; every future UI ticket that animates is saved a manual recording/compression step, and the dashboard side costs nothing further since its gallery and video parsing already exist. Runs on mac-mini-1 (already builds/screenshots/tests, per `ios-app.md`'s machine table) — no new machine.

**More capable, not more passive:** closes the exact slip #374 was meant to prevent for anything that *moves* — Gil still approves nothing he hasn't seen in motion, instead of a still that hides a broken transition.

## Tests first

**Python** (`lib/tests/test_evidence_capture.py`, following the existing `FakeRun`-injection convention from `test_simulator_capture.py`/`test_ios_evidence.py`):
1. A scene listed in `cfg["recordings"]` (`[{scene, seconds}]`) is captured via `simctl io booted recordVideo` for each configured appearance, converted to one GIF + one MP4, both paths returned in `shots` with a caption.
2. **ffmpeg missing** (`shutil.which("ffmpeg")` → `None`): that scene's capture raises `RuntimeError("ffmpeg not found")`, caught by `Measurer.evidence()`'s existing broad except and reported as `{"na": False, "error": ...}` — ticket not failed.
3. **Recording never stops**: the `recordVideo` subprocess is killed (SIGINT, then SIGKILL after a grace window) at `seconds` + a fixed cap, never waited on indefinitely.
4. **Scene crashes mid-recording**: the app process is gone before the recording is stopped → that scene reports "app exited mid-scene," not a GIF of a crashed/blank screen; other scenes still complete.
5. **Simulator already recording / busy** (two tickets at once against the same configured simulator name): the second attempt is refused with a plain error via a lockfile keyed on the simulator name, not left to corrupt either file.
6. **GIF > 8 MB / MP4 > 50 MB**: rejected per the cap-behavior Decision below, with a plain size reason, never silently committed.
7. **Bad/empty/malformed config**: a `recordings` entry naming a scene absent from `scenes`, a non-positive or absurdly large `seconds` (e.g. 0, -1, 99999), or a non-list value is refused with `ValueError`, matching the existing `"evidence.dev.ios_simulator needs ..."` style.
8. **Partial failure**: one scene's recording fails while another's still/recording succeeds → `Measurer.evidence()` still returns the successful shots; `_format_dev_evidence` renders the failed one as an inline warning line rather than crashing on a missing `path` key.
9. **Stale state**: a leftover `.mov`/partial file from a previous killed run in the same evidence dir is overwritten/cleaned, not mistaken for this run's output.
10. **Wrong permissions**: `docs/evidence/` (or its per-worktree subdir) not writable → `EnvMissing`/plain error, same as `simulator_capture.py`'s existing write-test pattern — `evidence_capture.py` currently lacks this check and should gain it.
11. Regression: `ticket_touches_ui`/`ui_files`/plain-screenshot-only scenes behave exactly as before.

**JS/Node** (`dashboard/test/`):
12. **Gate stays image-or-video** (`dashboard/test/ui_evidence.test.js`, mirrored in `lib/tests/test_pr_images.py`): a PR body containing only a `<video src=".../demo.mp4">` tag, a bare `.mp4` link, or a GitHub user-attachment video link passes `assertUiEvidence`/`verdict` — today it fails `NO_UI_EVIDENCE`; this is the fix, not a feature.
13. **Animation/transition diff, stills only → warns, doesn't block**: a PR touching a file matched by the motion-detect heuristic (Decision below) with only a PNG gets a new non-blocking advisory; Approve stays enabled (unlike `needsImages`, which disables it).
14. Same diff **with** a GIF/MP4 attached → no advisory.
15. A **non-animation** UI diff with only stills → no advisory (no false positive on an ordinary static screen change).
16. **Malformed/huge PR body**: the new video-shape regexes respect `pr_images.js`'s existing `MAX_BODY`/item caps rather than scanning unbounded input.
17. **gh/GitHub unreachable** while checking evidence: fails closed exactly as today's `UI_EVIDENCE_UNCHECKED` path (regression guard).
18. **CDP screencast recording** (new/extended `dashboard/test/cdp_capture.test.js`): the generalized screencast-to-MP4 helper produces a valid file for a short scripted interaction; Electron exiting mid-recording is reported, not hung (mirrors `captureViaCdp`'s existing exit-detection tests).

## Decisions
<!-- marvin:decisions -->
### cap-behavior: A recording that comes out over its size cap (GIF > 8 MB, MP4 > 50 MB) — what should happen?
- [ ] A: Reject that scene's recording outright, reported as a per-scene capture failure in the PR (same path as a broken driver); no auto-compression attempted
- [ ] B: Retry once at a lower resolution/fps before giving up, then reject if still over cap

### motion-detect: How should "diff touches animation or transition code" be detected, for the stills-only warning (and for deciding when the dashboard capture bothers recording video at all)?
- [ ] A: Filename/path heuristic only (names matching `motion|animat|transition`, mirroring the existing `merge_motion.js`/`MergeMotion.jsx` convention) — simplest, may miss an animation added to a plainly-named file
- [ ] B: Filename heuristic plus a content check on added diff lines (`@keyframes`, `transition:`, `animation:`, known motion-library imports) — catches more, costs one extra diff fetch per UI PR
<!-- /marvin:decisions -->

## Task List

1. **iOS recording capture**: extend `lib/evidence_capture.py::capture_ios_simulator`/`_capture_ios` to accept `cfg["recordings"]: [{scene, seconds}]`; run `simctl io booted recordVideo` around the scene's launch, stop it after `seconds` with a kill-after-timeout guard, validate config (bad scene name, bad `seconds`) with `ValueError`.
2. **ffmpeg conversion + size caps**: convert each recording to one MP4 (libx264) and one GIF (two-pass palette, reusing `record.mjs`'s exact filter graph); require `ffmpeg` up front; enforce caps per the `cap-behavior` Decision.
3. **Concurrency + hygiene guards**: a lockfile keyed on the simulator name so two tickets can't record the same device at once; clean up any stale partial file from a prior run; writability check on the evidence output dir (missing today).
4. **`capture_dev_evidence`/`Measurer.evidence()` shape**: let `shots` carry a per-item success-or-error so one failed scene doesn't drop the rest; update `mr_raiser._format_dev_evidence` to render a failed item as an inline warning instead of assuming a `path` key.
5. **Dashboard/Electron recording**: factor `merge_motion_evidence.mjs`'s `record()`/screencast-to-ffmpeg technique into a reusable helper (sibling to `dashboard/src/lib/cdp_capture.js`) and a `dashboard/scripts/capture_recording.mjs` next to `capture_screenshot.mjs`; trigger it for dashboard UI tickets flagged by the `motion-detect` heuristic (cost control — not every static dashboard change needs a video).
6. **Gate: recognize video evidence**: extend `ui_evidence.js::imageUrls`/`hasImage` and `lib/pr_images.py::image_urls` to recognize `<video>`/`<source>` tags, bare video-extension links and GitHub user-attachment video links, mirroring `pr_images.js`'s existing `VIDEO_EXT` pattern — the actual fix needed for "stays image-or-video."
7. **Stills-only-on-motion advisory**: add a non-blocking sibling to `dashboard/electron/main/mr_review.js::needsImages` (e.g. `motionNeedsVideo`) per the `motion-detect` Decision; render it as a lighter-tone sibling to `MrDetail.jsx`'s `NeedsImages`; never wire it into `prState.js`'s approve-blocking logic.
8. **Profile schema**: document `evidence.dev.ios_simulator.recordings` alongside the existing `scenes`/`appearances` keys in `config/playbooks/ios-app.md`/`.json` and wherever `evidence.dev` is validated in `project_profile.py`, same plain-`ValueError` style as today.
9. **Cleanup note**: file a short follow-up ticket flagging `lib/simulator_capture.py` as unwired dead code (found, not fixed, in this ticket).
10. Run the full Python + dashboard/vitest suites before marking done (main green is the one judge).
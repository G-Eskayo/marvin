## North-star fit

**Reuses before adding:**
- `evidence_capture.capture_ios_simulator` (`lib/evidence_capture.py:330-377`) — the existing boot/install/appearance/scene loop that already screenshots every scene in light+dark. The recording step rides the *same* booted simulator and installed app rather than booting a second one.
- The exact ffmpeg filter graphs already proven on the Mini in `dashboard/scripts/merge_motion_evidence.mjs:109-146` and `docs/design/merge-animation-757/record.mjs:54-58` (screencast/frames → mp4 → palette-based GIF). I'm lifting the palette command, not re-deriving it.
- `mr_raiser._format_dev_evidence` (`lib/mr_raiser.py:157-170`) already iterates a `shots` list and emits `![caption](url)` per item — a GIF/MP4 entry needs *zero* changes there, since the dashboard's own `PrImages.jsx`/`pr_images.js` already pick `kind: video` off the URL extension (`mp4|mov|m4v|webm`) independent of markdown syntax. **This means AC1 (dashboard renders an animated GIF in PR detail) is already satisfied by existing code** — confirmed by reading `dashboard/src/components/MrDetail.jsx:1-7,50-54` and `dashboard/electron/main/pr_images.js:16` — nothing to build there.
- `lib/pr_images.py`'s `_IMAGE_FILE` regex already includes `mp4|mov`, and `hasImage`/`image_urls` (both Python and `ui_evidence.js`) match on markdown-image *syntax*, not file extension — so `![caption](x.mp4)` already satisfies NO_UI_EVIDENCE today, because `pr-shots`/`_format_dev_evidence` always emit `!` syntax regardless of media type. **"The gate stays image-or-video" needs no code change — only a regression test** locking this in.
- `lib/fit_check.py`'s best-effort, non-blocking PR-comment/body-note pattern (reused conceptually, not by calling it) for the "warn when only stills" bullet — I'm folding the warning into the existing "Dev Environment Evidence" section text (`_format_dev_evidence`) rather than inventing a second gh API call or new dashboard wiring.

**Simplest sufficient approach:** one new small module (`lib/ui_recording.py`, ffmpeg wrapper + size caps) plus additions to `capture_ios_simulator`'s existing loop and one new pure function in `evidence_capture.py`. No new simulator-device-naming scheme, no macOS screen recording (see scope note), no dashboard/webhook-server changes.

**Resources:** recording+encoding adds real wall-clock time per UI ticket (simctl recordVideo + two ffmpeg passes); bounded by a hard 1–30s per-scene cap so it can't blow up a ticket's build time. No extra gh API calls (reuses the existing PR-body write).

**Phone-OS direction:** neutral — this is pipeline/evidence tooling, not user-facing.

**More capable, not more passive:** yes for the owner (Gil sees real motion before approving instead of trusting prose), neutral for the agent loop itself.

**Scope cut, stated plainly:** macOS native-app evidence (`capture_macos_app`, killer-sudoku) draws one off-screen frame via `-MarvinScreenshot` and quits — it never animates on-screen, so there is nothing to record without a wholly different capture contract. The ticket's "What to build" only lists iOS simctl and Web/Electron; macOS recording is out of scope for this pass. A profile that sets `evidence.recordings` while using `macos_app` gets a clear reported error, not a silent no-op.

## Decisions

Genuinely ambiguous: the ticket's "Web/Electron: Playwright video for the dashboard" bullet has no scene-declaration mechanism to hook into — marvin's own repo path (`run_ticket.py:318`, no project profile) just screenshots the built app once; there's no per-ticket config saying what to record or for how long, unlike iOS's named scenes. I'll ship the reusable record→GIF/MP4 capability (generalizing `merge_motion_evidence.mjs`'s screencast+ffmpeg into `lib/ui_recording.py`-equivalent JS) but need the owner to pick the trigger before it's wired into every dashboard UI ticket by default.

```markdown
## Decisions
<!-- marvin:decisions -->
### dashboard-record-trigger: How should the dashboard's own UI tickets decide to record a GIF/MP4 instead of (or in addition to) a still screenshot?
- [ ] A: Opt-in only — an executor that knows its change animates something sets an env flag/CLI arg on `capture_screenshot.mjs`; the default stays a plain screenshot. (what I'll build by default while this is pending)
- [ ] B: Always take a short fixed-length generic recording in addition to the still, for every dashboard UI ticket, regardless of whether it actually animates.
- [ ] C: Defer entirely — ship only the iOS recording path + the ffmpeg conversion library + the animation-warning note in this PR; dashboard auto-recording is a follow-up ticket once a scene-declaration mechanism exists for marvin's own repo.
```

## Tests (written first)

Ticket's "how we'll try to break it" + the Attacks list, plus standard misuse:

1. **Simulator already booted/busy (two tickets at once):** `recordVideo` against a device that reports "there is already an active recording" is caught and reported as *that scene's* recording failure — the already-captured stills (and other scenes' recordings) are not discarded.
2. **Recording never stops:** after the configured `seconds`, SIGINT is sent; if the recording process hasn't exited within a bounded grace period it's SIGKILLed and the scene is reported as failed ("recording did not stop cleanly"), never left hanging the pipeline.
3. **ffmpeg missing:** `shutil.which("ffmpeg")` returns `None` → a clear per-scene error ("ffmpeg not found...") is reported; the ticket's other evidence (stills, other scenes) is unaffected.
4. **Scene crashes mid-recording:** simctl's `recordVideo` exits early / writes a truncated `.mov` → the ffmpeg conversion step fails cleanly and is reported as that scene's error, not a crash of the whole capture.
5. **Bad/empty/malformed `evidence.recordings` config:** not a list; entries missing `scene`; `scene` not matching any name in `scenes`; `seconds` non-numeric, zero, negative, or absurdly huge (e.g. 99999) — all rejected with a clear `ValueError` at validation time, before any simulator work starts.
6. **Each dependency failing:** `xcrun`/`simctl` missing or erroring when starting the recording; disk full / unwritable `docs/evidence/` when ffmpeg tries to write output (OSError) — reported per scene, not raised to kill the ticket.
7. **Repeats:** capturing the same scene's recording twice (e.g. a re-run) doesn't collide on a stale `.mov`/`.gif`/`.mp4` left from a previous attempt — output paths are overwritten cleanly.
8. **Concurrency:** two concurrent `capture_ios_simulator` calls targeting the *same* configured simulator name, one with a recording in flight — the second's recording attempt fails with a clear "already recording" reason rather than corrupting or silently merging both tickets' footage. (Documented as a known, narrow limitation — not solving general parallel-dispatch device scoping here.)
9. **Size caps, GIF ≤ 8 MB / MP4 ≤ 50 MB:** a fake ffmpeg producing an oversized file triggers one automatic retry at reduced scale/fps; if still oversized, the scene is reported as a failure ("recording too large after compression"), never silently committed oversized and never silently dropped. A normal small output is *not* re-encoded a second time (no wasted work).
10. **NO_UI_EVIDENCE stays image-or-video (regression lock):** `pr_images.image_urls`/`hasImage` and `ui_evidence.js`'s `hasImage` already accept `![caption](x.mp4)` / `![caption](x.gif)` as satisfying evidence — a test proving this today, so a future change can't silently narrow it back to images-only.
11. **Animation-touch warning — true positive:** UI diff adds lines matching an animation/transition marker (`@keyframes`, `transition:`, `withAnimation`, `.animation(`, etc.) and `dev_evidence`'s shots are PNG-only → a warning line is appended to the Dev Environment Evidence section.
12. **Animation-touch warning — satisfied:** same diff, but shots include a `.gif`/`.mp4` → no warning.
13. **Animation-touch warning — true negative (most common case):** an ordinary static UI diff with no animation markers, PNG-only → no warning (must not be noisy).
14. **Animation-touch warning — defensive:** `dev_evidence` is `na`, has an `error`, is malformed, or the git diff call fails (not a repo, bad base ref) → never raises, returns no warning.
15. **Profile misuse:** `evidence.recordings` set while the profile's capture kind is `macos_app` → a clear reported error ("recordings aren't supported for macos_app yet"), not a silent no-op and not a crash.
16. **Existing behavior unchanged:** all current `test_ios_evidence.py`/`test_macos_evidence.py` cases (no `recordings` configured) still produce exactly the same still-only shots list as today.

## Task List

1. `lib/ui_recording.py` (new): `convert_to_gif_and_mp4(mov_path, out_dir, name, *, run=subprocess.run)` — checks `shutil.which("ffmpeg")`, runs the palette-based GIF pass and the MP4 pass (filters lifted from `merge_motion_evidence.mjs`), enforces `GIF_MAX_BYTES = 8*1024*1024` / `MP4_MAX_BYTES = 50*1024*1024` with one downscale retry before failing, returns `{"gif": path|None, "mp4": path|None, "error": str|None}`. Pure-ish: all subprocess calls go through the injectable `run`.
2. `lib/tests/test_ui_recording.py` (new): tests 3, 6, 9, 16-equivalent-for-this-module, each driven by a fake `run` (no real ffmpeg needed).
3. `lib/evidence_capture.py`: extend `capture_ios_simulator(worktree_path, cfg, recordings=None, run=..., sleep=..., popen=subprocess.Popen)` — after the existing still-screenshot loop, for each `(scene, appearance)` pair whose scene name appears in `recordings`: start `xcrun simctl io <device> recordVideo <tmp.mov>` via `popen`, let the scene play for `seconds`, SIGINT + bounded wait + SIGKILL fallback, then call `ui_recording.convert_to_gif_and_mp4`. Append successful GIF/MP4 paths as extra `shots` entries (`{"path", "caption"}`); append a `{"path": None, "caption": ..., "error": ...}` entry on failure so `_format_dev_evidence` can surface it — never raise out of the per-scene try/except.
4. Validate `recordings` up front in `capture_ios_simulator` (list of dicts, `scene` must match a declared scene name, `seconds` numeric in `[1, 30]`) — raises `ValueError` before any simulator work, mirroring the existing `required` tuple check style.
5. `lib/project_profile.py` `Measurer.evidence()`: read `evidence.get("recordings")`; pass it through to `capture_ios_simulator` when `kind == "ios_simulator"`; when `kind == "macos_app"` and `recordings` is non-empty, short-circuit with the explicit "not supported yet" error instead of calling `capture_macos_app`.
6. `lib/mr_raiser.py`: new pure function `evidence_capture.animation_touch_warning(worktree_path, dev_evidence, base_branch="main")` (lives in `evidence_capture.py`, reuses `ui_files`/`changed_files`) — greps the added lines of the diff's UI files for an `ANIMATION_MARKERS` pattern list; returns a one-line advisory string when markers are found and no shot path ends in `.gif/.mp4/.mov/.m4v/.webm`, else `None`. Call it once in `raise_mr` (which already has `worktree_path`), append the result into the `dev_evidence` dict under a new `animation_warning` key before `open_pr` is called.
7. `lib/mr_raiser._format_dev_evidence`: render `dev_evidence["animation_warning"]`, when present, as an extra `⚠` line after the screenshots — same visual convention as the existing error/unreviewed lines.
8. `lib/tests/test_ios_evidence.py`: extend with tests 1, 2, 4, 5, 7, 8, 15 (recording-specific) plus regression test 16.
9. New/extended tests for 10-14 (regression lock on `hasImage`/`image_urls`, and the `animation_touch_warning` cases) — likely `lib/tests/test_pr_images.py` for #10 and a new section in `lib/tests/test_mr_raiser.py` or `test_ios_evidence.py` for #11-14.
10. `config/playbooks/ios-app.json`/`ios-app.md`: one line each noting the `evidence.recordings: [{scene, seconds}]` key next to the existing "A GIF for anything that moves" line (doc already states the requirement; just point at the config key), keeping the paired doc/JSON convention intact.
11. Post the Decisions block above once this plan becomes a PR, and build the dashboard/"Web/Electron" default per option A pending the owner's answer (an opt-in flag on `capture_screenshot.mjs`/the generalized recorder, never wired into the default per-ticket path) — out of this task list's required scope beyond stubbing the opt-in flag if time allows; if not, explicitly say in the PR that Web/Electron auto-recording is deferred to the Decision's answer.
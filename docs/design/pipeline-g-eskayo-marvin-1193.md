Now I have enough grounding to write the plan.

## North-star fit

**Reuses before adding anything new:**
- `lib/box_build.py`'s `SSH_OPTS`/`ssh_holding_stdin` pattern — this is MARVIN's existing way to run a real command on mac-mini-2012 from a Mac; the profiling capture reuses this instead of inventing a new SSH wrapper.
- The box's own self-logging convention (`~/.claude/logs/dashboard-linux.log`, `desktoplive.log`, written by `marvin-dashboard.sh`/`main.js`'s own `log()`) — the new CPU-profile log is one more line-per-sample in the same style, not a new subsystem.
- `github_feed.js` / `github_state.js` (marvin#954, #422) already implement the "calm degrade, no loop" behavior AC#3 asks for (`feedStatus`, `FeedError`, exponential backoff in `githubState`). `isPullOnlyNode`'s `platform !== 'darwin'` fallback (`github_feed.js:34-41`) already makes mac-mini-2012 pull-only even though `resolveDeviceId()` (`device_identity.js:12-20`) can't read a hardware UUID on Linux (`ioreg` is macOS-only) — tracing this through shows AC#3's mechanism already exists; the gap (if any) is a missing regression test, not missing code.
- `brain-map/desktop-live-linux/main.js:152`'s existing `app.disableHardwareAcceleration()` — precedent, on this *exact* hardware, for the fix this plan proposes for the sibling dashboard app, which has no such call.
- `boot_animation.js`'s existing `cancel()`/`hold()`/grace-timer machinery — the fix extends it with a bound, rather than replacing it.

**Why simplest sufficient:** no new dependency, no new logging subsystem, no profiler binary. `app.getAppMetrics()` (built into Electron) gives per-process type + `cpu.percentCPUUsage` directly, which answers AC#1 ("found with a profile") and AC#2 ("idle CPU logged over 2h") with one small addition, logged in the existing style.

**Tokens:** spends some now (two Electron processes under-instrumented today, so root cause must be confirmed on real hardware, not guessed) to avoid a future guess-and-check cycle burning more.

**User capability:** restores capacity Seal Speak's scoring/storage work needs on this box (north star 5) without taking any new manual steps from Gil — purely automated fix + logging.

**Which machine / why:** investigation and the targeted code fix happen here (worktree, any Mac); *verification* (the 2 h idle-CPU log, confirming which process was hot) must run **on mac-mini-2012 itself**, since that's the only place the symptom reproduces (old Intel iGPU + Linux Mesa driver). No other machine can stand in for it.

## What I found (grounds the plan, not yet a guessed root cause)

Two concrete, code-evidenced candidates, neither of which the ticket lets me simply assert as *the* cause without a profile:

- **H1 — GPU-process load:** `brain-map/desktop-live-linux/main.js:152` calls `app.disableHardwareAcceleration()` with the comment *"Ivy Bridge GPU: software canvas is steadier for a 24 fps ambient view."* `dashboard/electron/main/index.js` (the actual "Box dashboard" the ticket names) never calls this. Same box, same old Intel GPU, inconsistent mitigation.
- **H2 — renderer-process load:** `dashboard/src/lib/boot_animation.js`'s `tick()` is a `requestAnimationFrame` loop that stops only when `finish()` runs, which only happens when the WAAPI fade-out's `.finished` promise resolves. That promise never resolves while `held` stays true, and `held` is released only by a real `pointermove` leaving the hovered target, a click, or a keypress (`boot_animation.js:144-195`). A kiosk/wallpaper box with no human at the keyboard can get stuck here indefinitely — "hours" fits.
- **AC#3 ("gh auth login" loop):** traced `fetchOpenPrs` (`index.js:250-280`) — on mac-mini-2012, `githubFeed` is always truthy (pull-only detection doesn't even need a working hardware-UUID read; the Linux fallback in `isPullOnlyNode` covers it), so this function always takes `fetchOpenPrsFromMini`, which never calls `gh`. The `console.error('[mr] could not list PRs...')` the evidence quotes (`index.js:272`) is **only reachable on the non-feed path** — it looks unreachable today on this box. Likely the evidence predates marvin#954, or there's a cold-start race I haven't found; either way this needs a pinning test, not a guessed fix.

## Tests first

One per "How we'll try to break it" item plus the misuse cases the section didn't name. (The ticket has no "How we'll try to break it" section — the list below covers the Attacks-equivalent misuse for a CPU/degrade bug like this.)

1. `isPullOnlyNode` returns `true` for a Linux platform even when `resolveDeviceId` returns `null` (no hardware UUID readable) — **locks down** the mechanism AC#3 depends on, against a registry that's empty, missing, or has mac-mini-2012 missing/renamed.
2. `fetchOpenPrs`/`fetchOpenPrsFromMini`, given `githubFeed` truthy and a missing/stale/corrupt `github-feed.json` (each of `readFeed`'s existing problem states: `missing`, `unreadable`, stale `alive_at`): produces one calm status line, not a thrown unhandled error, and never calls `gh`.
3. Repeated calls to `fetchOpenPrsFromMini` with the same failure note don't re-log (`lastFeedNote` dedupe, `index.js:291-294`) — pins "not a loop" for the log, against a poller firing every `FALLBACK_POLL_MS`/`MR_LIST_REFRESH_MS` tick for hours.
4. `boot_animation`'s hold mechanism (extract into a pure, testable function alongside `boot_view.js`, matching that file's existing test-the-pure-logic convention): given `held = true` and no `pointermove`/click/key for longer than a max-hold bound, `release()` fires anyway. Covers: no mouse ever attached (box's real condition), a mouse that moves once then never again, a synthetic/ghost hover event Chromium fires under a still cursor (the scenario `boot_animation.js:190-191`'s own comment documents).
5. `tick()`'s RAF loop is bounded even if `finish()` is somehow never reached (belt-and-suspenders watchdog) — given a mocked `requestAnimationFrame` that runs 10,000 times, the loop self-cancels rather than running forever.
6. The new CPU-sampling logger: malformed/missing `app.getAppMetrics()` entries (empty array, a metric missing `cpu`, a huge array from a leak) never crash the sampler and never grow the log file unboundedly (same bounded-log pattern as `error_log.js`'s `maxBytes`/`keepLines`).
7. `app.disableHardwareAcceleration()` gating: only applied when the box's own host id/platform matches mac-mini-2012 (or Linux), never applied on a Mac — a test against `device_identity.js`'s registry-reading pattern, covering registry missing/corrupt/wrong platform.
8. Concurrency: two `checkStall`/`renderFrame`-style timers firing in the same tick (existing `desktop-live-linux` pattern) don't double-fire the new sampler if wired into the same process — guard against double-init if `app.whenReady()` resolves twice (StrictMode-style double effect, same risk `BootSequence.jsx:14` already guards against with its `request` singleton).

## Decisions

## Decisions
<!-- marvin:decisions -->
### scope: Which process(es) does this ticket's fix and profiling cover?
- [ ] A: `dashboard/electron` only (matches the ticket's title, "Box dashboard")
- [x] B: Both `dashboard/electron` and `brain-map/desktop-live-linux` (the evidence's "live brain-map animation" suspect is the *other* Electron process on this box; `top` can't tell them apart from the name "renderer" alone)

**Rationale:** H1 suspects GPU acceleration in both processes; H2 suspects renderer process loops. Both processes need instrumentation to distinguish them; sampling both costs little and answers the question definitively.

### hold-bound: Max time the boot animation may stay held open on a hover before it force-releases (text, optional)
<!-- default if unanswered: 8000 ms -->
8000 ms (default)

## Task List

1. Add a lightweight CPU/GPU-process sampler to `dashboard/electron/main/index.js` (and, pending the `scope` decision, `brain-map/desktop-live-linux/main.js`): `app.getAppMetrics()` on an interval, appended to a bounded log file in the existing `~/.claude/logs/` style.
2. Write tests 6, 7, 8 above for the sampler before wiring it in.
3. Deploy to mac-mini-2012 (reusing `lib/box_build.py`'s `SSH_OPTS`/`ssh_holding_stdin` pattern to push/restart) and capture a real profile — confirms or kills H1 and H2, and starts the 2 h idle-CPU clock for AC#2.
4. Write test 1–3 (pull-only detection, feed-degrade states, log dedupe) pinning the already-working AC#3 mechanism; fix only if a test exposes a real gap (the cold-start race I couldn't rule out by reading alone).
5. If the profile confirms H1: add `app.disableHardwareAcceleration()` to `dashboard/electron/main/index.js`, gated per the `scope`/host decision; write test 7 against it.
6. If the profile confirms H2: extract the hold/release decision in `boot_animation.js` into a pure function beside `boot_view.js`, add the max-hold bound from the `hold-bound` decision, and the RAF watchdog; write tests 4–5 against the extracted logic.
7. Re-run the sampler on mac-mini-2012 for a full 2 h idle window; attach the log as the AC#2 evidence.
8. `marvin-show` the before/after CPU log to Gil instead of describing it in prose.
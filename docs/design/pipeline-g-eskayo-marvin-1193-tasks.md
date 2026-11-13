1. Add a lightweight CPU/GPU-process sampler to `dashboard/electron/main/index.js` (and, pending the `scope` decision, `brain-map/desktop-live-linux/main.js`): `app.getAppMetrics()` on an interval, appended to a bounded log file in the existing `~/.claude/logs/` style.
2. Write tests 6, 7, 8 above for the sampler before wiring it in.
3. Deploy to mac-mini-2012 (reusing `lib/box_build.py`'s `SSH_OPTS`/`ssh_holding_stdin` pattern to push/restart) and capture a real profile — confirms or kills H1 and H2, and starts the 2 h idle-CPU clock for AC#2.
4. Write test 1–3 (pull-only detection, feed-degrade states, log dedupe) pinning the already-working AC#3 mechanism; fix only if a test exposes a real gap (the cold-start race I couldn't rule out by reading alone).
5. If the profile confirms H1: add `app.disableHardwareAcceleration()` to `dashboard/electron/main/index.js`, gated per the `scope`/host decision; write test 7 against it.
6. If the profile confirms H2: extract the hold/release decision in `boot_animation.js` into a pure function beside `boot_view.js`, add the max-hold bound from the `hold-bound` decision, and the RAF watchdog; write tests 4–5 against the extracted logic.
7. Re-run the sampler on mac-mini-2012 for a full 2 h idle window; attach the log as the AC#2 evidence.
8. `marvin-show` the before/after CPU log to Gil instead of describing it in prose.
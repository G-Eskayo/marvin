## North-star fit

**Reuses before adding anything new:**
- `app.disableHardwareAcceleration()` — `brain-map/desktop-live-linux/main.js:152` already does this on mac-mini-2012's Ivy Bridge GPU ("software canvas is steadier for a 24 fps ambient view"). The sibling app the ticket actually names, `dashboard/electron/main/index.js`, has no such call. Same box, same old Intel GPU, inconsistent mitigation — this is the fix to extend, not invent.
- `dashboard/src/lib/boot_animation.js`'s existing `cancel()`/`hold()`/grace-timer machinery (`boot_view.js` holds its pure decisions) — extend with a bound, don't replace.
- `dashboard/electron/main/error_log.js`'s bounded-append idiom (`appendFileSync` + `if (size > maxBytes) keep last keepLines lines`) — the new CPU-sample log reuses this exact two-line idiom instead of writing a new byte-range-scanning trimmer.
- `lib/box_build.py`'s `SSH_OPTS` constant — real command on mac-mini-2012 reuses these SSH options (`BatchMode`, `ConnectTimeout`, `ServerAliveInterval`), not `box_build.py`'s VM-build machinery itself, which builds *tickets* in disposable VMs and doesn't fit "SSH into the live host, restart its running GUI app, read its log 2h later."
- `dashboard/test/polling_guard.test.js`'s allowlist escape hatch ("every timer... is a trigger, a UI clock, or allowlisted with its count and a reason") — the sampler's `setInterval` is a real exception to [[feedback-trigger-based-not-polling]] (there is no event to hang CPU sampling off), same category the guard already allows for.
- `github_feed.js` / `isPullOnlyNode` / `feedOnlyGh` (marvin#954, merged **2026-11-02**) already implement AC#3's "calm degrade, no loop" mechanism in full: on Linux, `resolveDeviceId()` returns `null` (`ioreg` doesn't exist there), `isPullOnlyNode` falls back to `platform !== 'darwin'` → `true`, and `fetchOpenPrs` (`index.js:253-254`) short-circuits to `fetchOpenPrsFromMini`, which **never calls `gh`** (`feedOnlyGh` only throws). The `console.error('[mr] could not list PRs...')` line the evidence quotes (`index.js:275`) is on the *other* branch, unreachable once `githubFeed` is truthy.

**Correction to the prior attempt's finding:** that attempt's plan said the evidence "possibly predates marvin#954" — checked against git history, it doesn't: #954 merged 2026-11-02, the evidence is from 2026-11-09, a week later. So the gh-auth-login-shaped error isn't explained by stale understanding of the code; the two live candidates are (a) **a stale deploy**: `config/mac-mini-2012/marvin-dashboard.sh` rebuilds before every launch but "a failed build still opens the last good build if there is one" — if a build has been silently failing on that box since before #954, it could still be running pre-#954 code; (b) a different, not-yet-found call site. This needs a real check of the box's `dashboard-linux.log` for "build failed" lines and the running build's commit, not another guess from reading main's code — this is now a task-list item, not a closed finding.

**Why simplest sufficient:** no new dependency, profiler binary, or logging subsystem. `app.getAppMetrics()` is built into Electron and gives per-process type + `cpu.percentCPUUsage` directly — one small, reused-pattern addition answers AC#1 and AC#2.

**Where this spends/saves tokens:** spends some now (a real 2h deploy+observe cycle on real hardware, because AC#1 explicitly forbids guessing) to avoid the failure mode of the **two previous attempts on this exact ticket** (2026-11-10 and 2026-11-18 retries), both of which built test-covered scaffolding (`cpu_sampler.js`, `boot_hold.js`, 34 tests) but never executed the real deploy-and-profile step, leaving AC#1/AC#2 unmet — which is the likely reason code review sent both back. This plan makes the live deploy+profile a sequenced, non-optional task, not a "next steps" appendix.

**User capability:** restores CPU/thermal headroom mac-mini-2012 owes Seal Speak's scoring/storage work (north star 5), with no new manual step for Gil.

**Which machine / why:** code changes happen in this worktree; **real verification runs on mac-mini-2012 itself** (`ssh mac-mini-2012`, Kali Linux, ADR 0069) — only that box's Ivy Bridge GPU and Mesa driver reproduce the symptom.

## Tension worth naming

Adding a permanent 5s `setInterval` sampler to a long-lived process sits against [[feedback-trigger-based-not-polling]] ("no rolling/polling checks anywhere"). CPU usage has no natural event to hang off, so this is a justified exception of the same shape `polling_guard.test.js`'s own allowlist already exists for — but it's a real tension, not a free pass, so it's called out explicitly rather than quietly added. The **sampler-lifetime** decision below lets the owner choose whether it's permanent (future-regression visibility, negligible cost) or removed once AC#2's evidence is captured.

## Tests first

1. `isPullOnlyNode` returns `true` for Linux even when `resolveDeviceId` returns `null` (no hardware UUID) — pins the mechanism AC#3 depends on against a registry that's empty, missing, or has mac-mini-2012 missing/renamed/misconfigured (e.g. `accepts` wrongly includes `'general'`).
2. `fetchOpenPrsFromMini`, given each of `readFeed`'s problem states (`missing`, `unreadable`, stale `alive_at`), produces one calm status line and never calls `gh` — against a missing/corrupt/stale `github-feed.json`.
3. Repeated calls with the same failure note don't re-log (`lastFeedNote` dedupe) — pins "not a loop" against a poller firing every tick for hours.
4. The hold/release controller (pure function extracted beside `boot_view.js`): given `held = true` and no `pointermove`/click/key past a max-hold bound, `release()` fires anyway. Covers: no mouse ever attached (the box's real condition), a mouse that moves once then never again, and Chromium's synthetic `pointerover` under a still cursor (`boot_animation.js:204-205`'s own documented case).
5. `tick()`'s RAF loop is bounded even if `finish()` is never reached (belt-and-suspenders watchdog): a mocked `requestAnimationFrame` run 10,000+ times self-cancels rather than running forever.
6. The CPU sampler never crashes and never grows its log unboundedly on: empty `getAppMetrics()` array, an entry missing `cpu`/`percentCPUUsage`, non-numeric values, a huge/leaking array, and `getAppMetrics()` throwing.
7. `app.disableHardwareAcceleration()` is called only when `process.platform === 'linux'`, never on `darwin` — a test against both platform values, not a registry lookup (simpler: Mac hardware never needs this; only the Linux box's Ivy Bridge GPU does).
8. Calling the sampler's start function twice (module-level, not just per-instance) does not create two independent interval timers — covers `app.whenReady()` resolving twice and any accidental double-wire into both `main.js` files.
9. `polling_guard.test.js`'s allowlist is updated with the sampler's file, exact interval count, and reason — a test that the guard still passes (and fails if a second, un-allowlisted interval is added later).
10. The log append reuses `error_log.js`'s bounded-append shape (`maxBytes` + `keepLines`, newest lines kept) rather than a new byte-scanning trimmer — a test with a tiny `maxBytes` confirms old samples are dropped, not the whole file lost.

## Decisions
<!-- marvin:decisions -->
### scope: Which process(es) get the CPU-sampler fix and instrumentation?
- [ ] A: `dashboard/electron` only (matches the ticket's title, "Box dashboard")
- [x] B: Both `dashboard/electron` and `brain-map/desktop-live-linux` (the evidence's "live brain-map animation" suspect is the *other* Electron process on this box; `top` can't tell them apart from the name "renderer" alone, and both samplers cost negligible overhead)

**Rationale:** carried over from the prior attempt's plan, unchanged — still the right call on the evidence.

### hold-bound: Max time the boot animation may stay held open on a hover before it force-releases
<!-- default if unanswered: 8000 ms -->
- [ ] 5000 ms
- [x] 8000 ms (default)
- [ ] 15000 ms

### sampler-lifetime: Should the CPU sampler stay in the app permanently, or run only through this ticket's verification and then get removed?
- [ ] A: Permanent (future-regression visibility on both Electron processes; cost is a few bytes/5s)
- [ ] B: Remove it once AC#2's 2h idle-CPU evidence is captured and attached (minimal permanent footprint)

### deploy-window: How should the real 2h idle-CPU verification on mac-mini-2012 run, given this agent session can't block for 2 hours?
- [ ] A: This session deploys the fix+sampler now, then a scheduled follow-up check (cron) reads the box's log after 2h+ and attaches the evidence to this ticket/PR
- [ ] B: This session deploys now and hands off an explicit manual step for Gil to confirm after 2h (no scheduled follow-up)

## Task List

1. On mac-mini-2012 (`ssh mac-mini-2012`), check `~/.claude/logs/dashboard-linux.log` for recent "build failed" lines and the currently-running build's git commit, to settle whether the evidence's gh-auth-login-shaped error came from a stale pre-#954 build or a still-unfound call site — don't re-assert "predates the fix" without checking.
2. Write tests 6, 8, 9, 10 (sampler resilience, module-level singleton guard, polling-guard allowlist, bounded-log reuse) before writing the sampler.
3. Add the CPU/GPU-process sampler (`app.getAppMetrics()` on a 5s interval, reusing `error_log.js`'s bounded-append idiom) to `dashboard/electron/main/index.js` and, per the `scope` decision, `brain-map/desktop-live-linux/main.js`; wire the module-level singleton guard from test 8; add the file+reason to `polling_guard.test.js`'s allowlist.
4. Write tests 1-3 (pull-only detection, feed-degrade states, log dedupe) pinning the already-working AC#3 mechanism — fix only if a test exposes a real gap.
5. Write tests 4-5 (hold-bound, RAF watchdog); extract the hold/release decision in `boot_animation.js` into a pure function beside `boot_view.js`, add the max-hold bound from the `hold-bound` decision and the RAF watchdog.
6. Write test 7; add `app.disableHardwareAcceleration()` to `dashboard/electron/main/index.js`, gated on `process.platform === 'linux'`.
7. Deploy to mac-mini-2012 over SSH (reusing `lib/box_build.py`'s `SSH_OPTS`), restart both Electron processes, and capture a real profile — confirms or kills H1 (missing GPU mitigation) and H2 (unbounded boot-animation hold), satisfying AC#1.
8. Per the `deploy-window` decision: either schedule the 2h follow-up read-back now, or hand off the manual confirmation step explicitly.
9. Once the 2h idle-CPU log comes back under 10%, attach it as AC#2's evidence; per the `sampler-lifetime` decision, either leave the sampler running or remove it.
10. `marvin-show` the before/after CPU log to Gil instead of describing it in prose.
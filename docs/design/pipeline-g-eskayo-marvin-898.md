## North-star fit

**Reuses, before adding anything new:**
- `lib/peer_care.py`'s existing SSH-push pattern (`im_back()`, `_ssh`, `ts_host`, `watched_by`) for the new "sleep/off word" push — same transport, same trust model, no new channel.
- `lib/peer_care.py`'s existing `handle()` lock/budget/`job_events` machinery — the fix-ladder, attempt budget and `notify_owner` escalation are untouched; the new code only adds a calm early-exit before that machinery runs.
- `brain-map/DesktopLive/main.swift`'s existing `NSWorkspace` sleep/wake observer (`observeSystemEvents()`, already registered for `willSleepNotification`/`didWakeNotification` and already running on **both** the Mini and the laptop per `job_catalog.py`'s `"desktoplive": {"machine": "both", ...}`) — this is the actual trigger source for "before it sleeps / when it wakes"; nothing new needs installing.
- `main.swift`'s existing debounce idiom (`scheduleReconcile`, cancel-and-reschedule `DispatchWorkItem`) for "a rapid sleep/wake cycle must not flood events" — same idiom, not a new timer.
- `health_checks.py`'s existing `severity: "asleep"` (already rendered distinctly, blue moon icon, in `dashboard/src/components/HealthDashboard.jsx:21-41` — "deliberately NOT red") and its existing `kind == "laptop"` vs always-on distinction (`classify_unreachable`) — the new Vitals check reuses this severity value and the registry's existing `kind` field (`machine_profile`/`_registry()`), so **zero frontend changes**.
- `docs/design/847-health-card/README.md`'s own stated extension point: "a `health_checks.py` check per Mac (`care:<device>`)" — this ticket builds exactly that, not a new mechanism.
- ADR 0081 decision 1 ("every registered device is a watcher of every other") — the mesh in `config/peer_care.json` is config-only, not new code.

**Simplest sufficient approach:** no new transport, no new daemon, no new UI. The "word" is a local JSON file write on the receiving watcher (no network call in the check itself) plus a best-effort SSH push on the sending side, reusing code that's already time-pressure-tolerant by design (ADR 0081's own "I'm back" push already accepts best-effort delivery).

**Resource cost:** spends nothing new at rest — one more idle IPN reader on the laptop (already the pattern for the Mini/2012), and the Vitals check does a local file read, not a probe. Saves an SSH round-trip per incident where today a sleeping Mac would otherwise get probed by the fix ladder.

**More capable, not more passive:** Gil stops having to mentally discount "is that red because the laptop is just closed?" — the system now says so itself, and a real crash (vs. a normal lid-close) is distinguishable without him checking.

**Where it runs:** laptop gets its own `watch-ipn`/`im-back` LaunchAgents (same generic plists already in `config/launchd/`, now also bootstrapped there — a manual one-line `launchctl bootstrap` on the physical laptop, like the existing `UNLOCK_SETUP` precedent, not something this PR's code can execute). The Vitals sweep itself stays Mini-only, per the existing `job_catalog.py` `"health-check": {"machine": "mini", ...}` entry — unchanged.

## Decisions

None needed. ADR 0081 (mesh, trigger-only, fix ladder, `job_events`) and CONTEXT.md's Vitals section (the exact three Mac states, "laptop never red," "Mini red only after grace") already pin down every choice this ticket requires. Scoping notes I'm making as plain engineering calls, not asking Gil to pick: the 2012 mini (Linux, no DesktopLive) only *receives* words, never sends them (it isn't expected to sleep — ADR 0081 context); cross-machine Vitals *rendering* when the Mini itself is the one gone quiet is satisfied at the peer_care/notification layer on the laptop and 2012 (each already has its own local incident + the existing `notify_owner` alert path), not a new multi-machine UI, matching the same "MARVIN Mobile isn't built yet, so it isn't part of this" boundary the issue already draws.

## Tests first

`lib/tests/test_peer_care.py`:
1. `test_watched_by_reads_the_config` — **update**, not add: with the new mesh config, `watched_by("macbook-pro-1", CFG)` now returns `["mac-mini-1", "mac-mini-2012"]`, not `[]`. (The old comment "the laptop isn't a watcher" is the thing this ticket overturns.)
2. A fresh `asleep`/`off` word, then the IPN "offline" trigger fires → `handle()` returns calmly (no incident opened, no fix run, no `tell`), state surfaces as `asleep`/`off`, never `told`/red. (*Acceptance: laptop shutdown/lid-close shows "off/asleep · last seen", never red.*)
3. No word at all, peer goes offline → `mac_state()`/`handle()` path reports `gone quiet`, and for an always-on `kind` this still feeds the existing attempt budget/notify path unchanged. (*Acceptance: a Mac that crashes with no sleep word shows "gone quiet".*)
4. **Word lost before send** ("the sleep word is lost because the Mac sleeps before it's sent"): no word on file, but the peer's `kind` is `"laptop"` → `mac_state()` still doesn't escalate to red (stays `gone quiet`/yellow, never red) — a laptop is never shown as dead or failing even when the word never arrives.
5. **Tailscale down on this watcher** (own probe can't be read): `mac_state()`/`classify()` return `unknown`, never `gone quiet` or `healthy` — we don't accuse a peer we can't actually see.
6. **Split network** (both sides think the other is down): a single unexplained "offline" edge does not itself call `tell_owner` — only after the existing `attempts_per_incident` budget is spent (reuses `test_three_attempts_then_it_stops_and_tells_the_owner_once`'s existing guarantee; new test confirms the word/gone-quiet path goes through the same budget, not a shortcut).
7. **Rapid sleep/wake flood**: sending the same peer's word rapidly N times leaves exactly one word record (last-write-wins, no growing list/log), and `expect-asleep`'s receiver does no probing/SSH itself (cheap, local-only), so a flapping peer can't fan out N SSH calls from the receiving side.
8. A stale word (older than a bound, or superseded by a later `healthy` probe already on file) is treated as expired — a peer that announced "asleep" and then genuinely crashed without ever waking is *not* masked as calm forever past that bound.
9. `expect-asleep` with a malformed `--word` value, or a peer id not in the registry, or a peer id containing path-traversal characters (`../`, absolute path) → rejected/ignored safely, no write outside `STATE_DIR` (mirrors the existing `test_unlock_script_refuses_a_peer_name_that_could_be_a_path` precedent).
10. Clearing a word that was never set, or clearing twice, is a safe no-op (same shape as the existing `_save_incident(..., {})` idiom).
11. `handle()` on a `healthy` probe clears any stored word (so a later real offline edge isn't masked by a week-old "asleep").
12. `expect_asleep()` (the sender) pushes to all watchers concurrently with a bounded timeout and returns even if one watcher's SSH hangs — a slow/unreachable watcher can't block the others or the caller past the existing per-call timeout.

`lib/tests/test_health_checks.py`:
13. `check_peer_watch()` for a peer with a fresh `asleep`/`off` word → one result per watched peer, `severity == "asleep"`, detail mentions "last seen".
14. `check_peer_watch()` for a `gone quiet` peer with `kind == "laptop"` → `severity == "yellow"`, never `"red"`.
15. `check_peer_watch()` for a `gone quiet` always-on peer whose incident has exhausted its attempt budget → `severity == "red"`; within budget → `"yellow"`.
16. `check_peer_watch()` with no peer_care state on disk yet (fresh install) → a safe "not enough data yet" result, not an exception (the `guarded()` wrapper is a backstop, not where this should be caught).
17. `check_peer_watch()` on a machine that watches nobody (`cfg["watch"].get(me, [])` empty) → returns `[]`/`None` cleanly.
18. Full `run_all()` sweep still runs to completion with the new check included (no import/wiring break).

`brain-map/DesktopLive/tests/PeerWordTests.swift` (new, paired with a new small `PeerWord.swift`, mirroring the existing `EventLogTests.swift`/`RecoveryTests.swift` pattern and wired into `test.sh`):
19. Pure mapping: `"sleep"` → `expect-asleep <me>`, `"poweroff"` → `expect-asleep <me> --word off`, `"wake"` → `im-back` args.
20. Debounce: a sleep notification immediately followed (before the debounce fires) by a wake notification coalesces to **no sleep word sent at all** (just the wake), so a quick lid-close-then-open doesn't flap Vitals.

## Task List

1. `config/peer_care.json`: change `"watch"` to the full mesh (`mac-mini-1`, `mac-mini-2012`, `macbook-pro-1` each watching the other two).
2. `lib/peer_care.py`: add `word_path`/`load_word`/`_save_word` (state I/O, mirroring `_incident_path`/`load_incident`/`_save_incident`); add `expect_asleep(cfg, word="asleep", push=_ssh)` (sender, loops `watched_by`, concurrent, bounded timeout); add the `expect-asleep <peer> [--word asleep|off]` CLI subcommand (receiver: validate peer/word, write word, light `job_events` step, no probe); add `mac_state(peer, cfg, state_dir)` (pure, Vitals-facing: `awake`/`asleep`/`off`/`gone quiet`/`unknown` + `last_seen`); modify `handle()` to short-circuit calmly when a fresh asleep/off word covers the current offline trigger, and to clear the word on a `healthy` probe; wire `expect-asleep` into `main()`.
3. `lib/tests/test_peer_care.py`: write tests 1–12 above (update the one stale test, add the rest).
4. `brain-map/DesktopLive/PeerWord.swift` + `tests/PeerWordTests.swift`: pure event→args mapping and debounce decision; update `test.sh` to build/run the new pair.
5. `brain-map/DesktopLive/main.swift`: extend `observeSystemEvents()`'s event list with `NSWorkspace.willPowerOffNotification` → `"poweroff"`; in the switch, call a new debounced `schedulePeerWord(label)` (same cancel-and-reschedule idiom as `scheduleReconcile`) that shells out (fire-and-forget `Process`, no `waitUntilExit`) to `~/.agents/venv/bin/python ~/.agents/lib/peer_care.py <args from PeerWord.swift>`.
6. `lib/health_checks.py`: add `check_peer_watch()` (reads `peer_care.load_config()`/`mac_state()` per watched peer, local-only, no network) returning `care:<device>` results per the severity mapping (awake→green, asleep/off→`"asleep"`, gone quiet→yellow/red per existing incident/attempt state); wire it into `default_checks()`.
7. `lib/tests/test_health_checks.py`: write tests 13–18 above.
8. `lib/job_catalog.py`: add `"peer-care-ipn"` and `"peer-care-im-back"` entries (`machine: "both"`, `goal: "ns3"`, reporter `job_events` `peer-care-<peer>`, consumer "Vitals / the owner") to close the existing uncatalogued-job gap this ticket extends to a new machine.
9. `config/launchd/com.marvin.peer-care-ipn.plist` and `com.marvin.peer-care-im-back.plist`: update header comments only, noting they now also run on the laptop (content is already machine-agnostic — no functional change).
10. Note for Gil (not a code task): the laptop's actual `launchctl bootstrap` of those two plists is a one-line manual step on the physical MacBook, same as the existing `UNLOCK_SETUP` precedent — flag this in the PR description so it isn't mistaken for "done."
# Plan: Peer watch — the laptop watches too, and Macs say "going to sleep" (marvin#898)

## North-star fit

**Reuses before adding anything new:**
- `lib/peer_care.py:watch_ipn`/`read_ipn` (trigger-based IPN-bus reader) — the new sleep/wake/shutdown reader (`watch-power`) copies this exact shape: one blocked reader, no timer, calling the same `handle()`.
- `lib/peer_care.py:im_back` (push-to-watchers-over-SSH pattern) — reused directly for "woke" (no new RPC needed); a lighter sibling (`announce`/`record-word`) follows the same remote-SSH-push shape for "sleep"/"shutdown".
- `lib/memory_guard.py:PressureSource` (ctypes against a system framework, zero new dependencies, event-driven) — this is the *exact* precedent for turning a macOS kernel notification (there: `DISPATCH_SOURCE_TYPE_MEMORYPRESSURE` via libdispatch) into a Python blocking source with no polling and no PyObjC. The new `PowerSource` class does the same thing against IOKit's `IORegisterForSystemPower`.
- `lib/health_checks.py:classify_unreachable` + `lib/device_status.py:device_statuses` (already produce the dashboard's per-Mac severity, already distinguish laptop vs always-on, already render "asleep · last seen N" in `DeviceColumns.jsx`/`describeDevice`) — this is the *existing, working* display pipeline for "awake/asleep/gone-quiet"; the ticket's "Vitals shows each Mac as awake, asleep, or gone quiet" acceptance criterion is a refinement of this pipeline, not a new one.
- `config/launchd/com.marvin.peer-care-ipn.plist` — copied verbatim in shape for the new `com.marvin.peer-care-power.plist`.

**Why simplest sufficient:** no new daemon framework, no new state store shape (one more small JSON file per peer, same pattern as `<peer>.facts.json`/`<peer>.last.json`), no new always-on GUI process. The alternative I rejected was hooking the Swift wallpaper renderer's (`brain-map/DesktopLive/main.swift`) existing `NSWorkspace` sleep/wake observer — rejected because it requires a graphical login session and exists to pause map rendering, not to carry a reliability signal; coupling peer-care correctness to a wallpaper app would make "gone quiet" detection silently depend on whether the desktop wallpaper happens to be running (Watts check: that mechanism would serve the wallpaper's own complexity, not peer-care's actual job).

**Where it spends/saves:** spends one new idle process per Mac (the IOKit reader), same order of cost as the existing IPN reader ("one idle process, ~0 CPU" per ADR 0081). It *saves* by deleting a guess: `health_checks.ASLEEP_MAX_HOURS`'s 72-hour heuristic exists today only because there was no real signal for "is this actually asleep or actually dead" — once a real word exists, the guess is replaced by ground truth (Colton check: find the real signal, not a louder proxy for it).

**Phone-OS direction:** neutral — this is Mac-to-Mac infrastructure, not phone-reachable, but it's exactly the kind of "every machine reports its own true state with no single hub" plumbing (north star 5) that a future phone client would read from, unchanged.

**More capable or more passive:** more capable — Gil currently loses truthful signal (a crashed laptop and a sleeping laptop look identical); this gives him an accurate "needs you" signal only when something actually needs him, which is also what lets Vitals *stop* bothering him on ordinary sleep/shutdown.

**Ticket's stated fit:** none stated explicitly beyond "extend `lib/peer_care.py` (ADR 0081)" — checked against the code and confirmed accurate; the extension point is real and the file is exactly where the IPN-bus / fix-ladder machinery already lives.

---

## Design (what gets built)

1. **Watch mesh**: `config/peer_care.json`'s `"watch"` grows from the Mini↔2012 pair to also include the laptop:
   ```json
   "watch": {
     "mac-mini-1": ["mac-mini-2012", "macbook-pro-1"],
     "mac-mini-2012": ["mac-mini-1"],
     "macbook-pro-1": ["mac-mini-1"]
   }
   ```
   (Mini↔laptop bidirectional; 2012↔laptop left unwired — see Decision `mesh-scope`.)

2. **The word**: two new tiny `peer_care.py` subcommands, mirroring `im_back`'s existing remote-push shape:
   - `peer_care.py announce <state>` (`state` ∈ `sleep|wake|shutdown`) — run **locally** by the machine about to change state; for each `w` in `watched_by(me, cfg)`, SSHes into `w` and runs `record-word`.
   - `peer_care.py record-word <peer> <state>` — run **on the watcher**, by the remote SSH call above; writes `var/peer-care/<peer>.word.json = {"word": state, "at": now}` (same atomic-write pattern as `_save_incident`/`refresh_facts`).
   - New accessor `load_word(peer, state_dir=STATE_DIR) -> dict`, mirroring `load_facts`/`load_incident`.

3. **`handle()` short-circuits on a fresh word.** Before probing, `handle()` reads `load_word(peer)`; if the latest word is `sleep` or `shutdown` and nothing newer supersedes it, it records the calm state and returns `{"action": "announced", "state": word, "fix": None}` **without probing, without opening an incident, without any fix ladder step** — this is what stops "a rapid sleep/wake cycle" from flooding `job_events` or firing WoL packets at a laptop someone just chose to close.

4. **Sleep/wake/shutdown trigger**: new `PowerSource` class in `lib/peer_care.py` (ctypes against `IOKit.framework`'s `IORegisterForSystemPower`, same technique as `memory_guard.PressureSource` against libdispatch — no PyObjC, no compiled helper) and `watch_power(me, cfg)`, which blocks on it and calls `announce("sleep"|"shutdown")` on `kIOMessageSystemWillSleep`/`kIOMessageSystemWillPowerOff`, and `im_back(me, cfg)` (reused as-is) plus `announce("wake")` on `kIOMessageSystemHasPoweredOn`. New `peer_care.py watch-power` CLI command, new `config/launchd/com.marvin.peer-care-power.plist` copied from `com.marvin.peer-care-ipn.plist`'s shape (`RunAtLoad`+`KeepAlive`, `ThrottleInterval`). macOS-only (`host_os.os_name() == "macos"`); the 2012 Linux mini is unaffected (it already only watches, never sleeps).

5. **Display: real signal replaces the guess.** `health_checks.classify_unreachable(kind, peer, now, grace_hours=0.0, word=None)` gets a new optional `word` parameter (backward-compatible default `None`):
   - a current `sleep`/`shutdown` word (no later word, i.e. not superseded by a `wake`) → `("asleep", ...)` / `("off", ...)` with `last_seen = word["at"]`, **for any kind**, never red. This replaces the laptop-only, duration-guessed `asleep` branch — the 72h `ASLEEP_MAX_HOURS` heuristic is deleted, since the real word makes it redundant.
   - no current word and unreachable → **"gone quiet"**: for `kind != "laptop"` (the Mini, and the 2012 if it's ever watched this way) the existing `grace_hours` yellow→red escalation is unchanged, just relabelled "gone quiet" in the detail text; for `kind == "laptop"` it is **never red** (new severity value, see Decision `gone-quiet-tone`).
   - both call sites (`device_status.py:device_statuses`, `health_checks.py:check_machine_reachability`) gain a `word_lookup`/lazy `peer_care.load_word(device_id)` call, the same shape as the existing `peer_lookup` parameter.

6. **Dashboard**: `dashboard/src/components/DeviceColumns.jsx`'s `describeDevice` gains label/tone entries for severities `"off"` and `"gone-quiet"` (`"Off"` / `"Gone quiet"`, with `detail` carrying `last seen ...` the same way `"asleep"` already does).

---

## Decisions

<!-- marvin:decisions -->
### mesh-scope: Should the 2012 Linux mini and the laptop watch each other too, or just Mini↔laptop?
- [ ] A: Mini↔laptop only (what's in this plan) — the 2012 and the laptop stay unwired to each other; simplest, and every acceptance criterion is met without it
- [ ] B: Full mesh — the 2012 also watches the laptop and the laptop also watches the 2012, so "every Mac is a watcher of every other" literally

### gone-quiet-tone: How should a laptop's "gone quiet" (crashed, no word) look in Vitals, distinct from "asleep"?
- [ ] A: Reuse the existing amber/yellow dot (today's "worth a look" tone), new label text "Gone quiet"
- [ ] B: A new, distinct dot colour just for "gone quiet", separate from both amber (missed purpose) and the sky-blue asleep dot

### word-ttl: Should an announced "asleep"/"off" ever expire back into attention-worthy, or stay calm forever (as CONTEXT.md's Mac-state definition literally reads) until the next real trigger?
- [ ] A: Stays calm indefinitely — no expiry, exactly as written ("never shown as dead or failing")
- [ ] B: Add a long-tail cutoff (e.g. the old 72h) after which an announced-but-still-gone Mac is shown as worth a look too
<!-- marvin:decisions -->

---

## Tests (written first)

**From "How we'll try to break it":**
1. `test_sleep_word_lost_because_mac_slept_before_it_was_sent` — `announce()`'s SSH push to a watcher times out/fails; the watcher still correctly classifies the peer as **gone quiet**, not calm asleep (no false calm).
2. `test_tailscale_itself_down_on_one_mac` — `tailscale_status()` returns `None` on the sender or the watcher; `announce`/`watch_power`/`handle` never raise, degrade to "can't check"/gone-quiet, same as today's `_CANT_CHECK` path.
3. `test_split_network_each_mac_thinks_the_other_is_down` — both sides independently classify the other as gone-quiet/unreachable; no crash, no deadlock, no double-fix (the per-peer lock already guards this — add a test that two *different* watchers of the same peer don't both run the fix ladder).
4. `test_rapid_sleep_wake_cycle_does_not_flood_job_events` — several `sleep`→`wake` announces in quick succession; `handle()`'s word short-circuit means zero `job_events` incident entries and zero fix-ladder calls are recorded for any of them.

**From the acceptance criteria, each as its own test:**
5. `test_classify_unreachable_laptop_shutdown_word_reads_off_never_red`
6. `test_classify_unreachable_laptop_sleep_word_reads_asleep_with_minutes_last_seen`
7. `test_watch_power_sleep_event_calls_announce_sleep_before_acknowledging` (and the shutdown equivalent)
8. `test_watch_power_wake_event_calls_im_back_and_announce_wake`
9. `test_read_ipn_or_watch_power_trigger_on_mini_offline_is_seen_by_both_laptop_and_2012_watchers` — extends the existing `test_ipn_reader_handles_down_edges_and_up_edges_with_an_open_incident` shape to the new two-watcher config.
10. `test_classify_unreachable_no_word_and_unreachable_is_gone_quiet_not_asleep` — replaces the old duration-based guess; a fresh unreachable peer with no word at all reads "gone quiet", not "asleep".
11. `test_gone_quiet_laptop_is_never_red` / `test_gone_quiet_always_on_mac_still_escalates_to_red_after_grace` — both halves of the Mac-state rule in one pair of tests.
12. `test_no_new_polling_loop` — a static check (grep-based, like existing "no `time.sleep` in a `while True` outside a bounded wait" tests elsewhere) that `watch_power`/`PowerSource` contains no `StartInterval`/timer-based retry, mirroring however `test_peer_care.py`/ADR 0081's existing tests assert trigger-only behaviour.

**Misuse the ticket didn't name, added per the north-star testing rule:**
13. `test_announce_with_a_peer_name_that_is_not_registered` — `record-word`/`announce` refuse or no-op on an unknown device id (same spirit as the existing `marvin-peer-unlock` path-traversal test).
14. `test_record_word_concurrent_writes_from_two_announces` — two announces racing (e.g. sleep then immediately wake) land the *later* timestamp, never corrupt the file (same atomic tmp+`os.replace` pattern already used everywhere else in this file).
15. `test_load_word_missing_or_malformed_file_is_treated_as_no_word` — mirrors `load_facts`'/`load_incident`'s existing `(OSError, ValueError)` → `{}` fallback.
16. `test_classify_unreachable_word_from_a_different_machine_is_ignored` — a stale word file whose `at` predates the peer's last confirmed online time doesn't mask a genuine later crash (clock-skew-style test, same spirit as `test_clock_skew_between_machines_cannot_reopen_or_expire_an_incident`).
17. `test_watch_power_survives_ioregisterforsystempower_failure` — IOKit call itself fails (e.g. sandboxed/no entitlement); the process logs and exits non-zero rather than crash-looping (covered by the existing `ThrottleInterval` pattern, but needs a unit test for the Python-side failure path).

Verify (per the repo's rule): a change to `classify_unreachable`, `handle`, `watch_power`, `announce`/`record-word`, or the `watch` config without one of the above tests changing counts as a verify failure.

---

## Task List

1. `config/peer_care.json`: add `macbook-pro-1` to `"watch"` per Decision `mesh-scope`; update its `"_doc"` comment.
2. `lib/peer_care.py`: add `load_word`/`_save_word`/`word_path` (mirrors `load_facts`/`load_incident`), `announce(me, state, cfg)`, `record-word` handling, and wire both into `main()`'s subparsers.
3. `lib/peer_care.py`: make `handle()` consult `load_word(peer)` before probing and short-circuit on a current `sleep`/`shutdown` word (no probe, no incident, one `job_events` step at most for visibility).
4. `lib/peer_care.py`: add `PowerSource` (ctypes/IOKit) and `watch_power(me, cfg)`; wire `sleep`/`shutdown` → `announce(...)`, `wake` → `im_back(...)` + `announce("wake")`. Add `watch-power` to `main()`.
5. `config/launchd/com.marvin.peer-care-power.plist`: new file, copied from `com.marvin.peer-care-ipn.plist`'s shape.
6. `lib/health_checks.py`: add `word` parameter to `classify_unreachable`; replace the laptop duration-guess branch with the word-based branch; delete `ASLEEP_MAX_HOURS` once superseded (or keep behind Decision `word-ttl` option B); wire `check_machine_reachability()` to pass `peer_care.load_word(device_id)`.
7. `lib/device_status.py`: add a `word_lookup` parameter to `device_statuses`, wire it in `main()` via `peer_care.load_word`.
8. `dashboard/src/components/DeviceColumns.jsx`: add `"off"`/`"gone-quiet"` label/tone/detail handling in `describeDevice` and the `DOT` map, per Decision `gone-quiet-tone`.
9. Write all tests listed above in `lib/tests/test_peer_care.py`, `lib/tests/test_health_checks.py`, `lib/tests/test_device_status.py`, and `dashboard/test/devices.test.jsx`, before the corresponding implementation step (TDD order: 2→tests for word storage; 3→tests for the short-circuit; 4→tests for the power source; 6→tests for classify; 7/8→tests for the display wiring).
10. Update `docs/adr/0081-macs-look-after-each-other.md`'s Context/Decision section with a short addendum note (the laptop is now a watcher; the word mechanism), and `CONTEXT.md`'s "Peer watch" bullet if its wording needs tightening after the owner answers the Decisions above.
11. Run the full Python test suite (`lib/tests/`) and the dashboard suite (`dashboard/test/`) before opening the PR, per the merge-gate rule.
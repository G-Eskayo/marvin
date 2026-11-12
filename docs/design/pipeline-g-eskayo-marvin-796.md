Confirmed — this is screenshot plumbing for PR evidence capture, already wired to a standard width-capture script. Now I have everything needed to write the plan.

## North-star fit

**Reuses:** `lib/health_checks.py:classify_unreachable()` and `_tailscale_peer()` (lines 1517–1565) — the exact "asleep vs. red" heuristic the ticket's evidence points at (`HealthDashboard.jsx:22-24`'s moon/sky severity already consumes its output for Health). `health_checks` is already imported as a library (not just run standalone) by `ticket_pipeline.py`, `failure_breaker.py`, `mirror_health.py`, `memory_guard.py` — importing it from `device_status.py` follows an established pattern, not a new one. On the frontend: `DispatchStatusBadge.jsx`'s `agoShort()` (currently unexported, used for "last: X (3 min ago)") for the "last seen" wording, and `HealthDashboard.jsx`'s `MoonIcon` for the asleep glyph — both get `export`ed and imported rather than re-implemented. `device_status.py`'s existing dependency-injection shape (`local`/`online`/`probe` callables, exercised by `test_device_status.py`'s `rows()` helper) is extended with the same pattern (`peer_lookup`, `now`), not replaced.

**Simplest sufficient approach:** `classify_unreachable` already distinguishes laptop-vs-always-on and has an `ASLEEP_MAX_HOURS` grace heuristic for laptops; it has no grace period at all for always-on machines (`kind != "laptop"` → immediate `"red"`, pinned by `test_always_on_desktop_offline_is_red` / `test_desktop_with_no_tailscale_state_stays_red`). Rather than duplicating classification logic for Activity, I extend the function with an optional `grace_hours` parameter (default `0`, preserving Health's exact existing behavior and its pinned tests byte-for-byte) that only changes behavior when a caller opts in. Activity's `device_status.py` opts in; Health's `check_machine_reachability()` doesn't change at all.

**Tokens:** spends a small amount reading/writing to extend a well-tested pure function rather than inventing a second classifier; saves on every future "why is this device red" question since Activity and Health now agree.

**Phone-OS direction:** neutral/small positive — makes the always-reachable Activity view trustworthy instead of crying wolf, which matters more as more machines join.

**User capability:** more capable — stops a false "something's down" read that currently requires Gil to manually check if it's just a closed laptop or a Tailscale blip.

## Files to touch (read in full before this plan)

- `lib/health_checks.py` — `classify_unreachable()` (1545–1565), `_tailscale_peer()` (1517–1542), `ASLEEP_MAX_HOURS` (1514), `check_machine_reachability()` (1574–1594, **unchanged** call site, confirms backward compatibility)
- `lib/device_status.py` — `device_statuses()` (49–94), `_row()` (33–43), `probe_remote()` (18–30), `main()` (97–124)
- `dashboard/src/components/DeviceColumns.jsx` — `describeDevice()` (6–10), `DOT` (17), render block (41–67)
- `dashboard/src/components/DispatchStatusBadge.jsx` — `agoShort()` (16–22, currently unexported)
- `dashboard/src/components/HealthDashboard.jsx` — `MoonIcon` (31–40, currently unexported), `SEVERITY_COLOR.asleep`/`.yellow` (22–27)
- `lib/tests/test_device_status.py`, `lib/tests/test_health_checks.py` (extend, don't break)
- New: `dashboard/test/*` for `DeviceColumns.jsx` tone rendering (check existing test file naming convention first — likely `dashboard/test/device_columns.test.jsx` or similar, matching sibling test files already in that directory)

## Decisions

```markdown
## Decisions
<!-- marvin:decisions -->
### grace: How long may an always-on Mac be unreachable before Activity turns it red (amber before that)?
- [ ] A: 5 minutes
- [ ] B: 15 minutes
- [ ] C: 30 minutes (matches cron_health's existing GRACE_MINUTES convention)

### cantcheck: When Tailscale itself can't be asked at all (CLI missing/failing), should an always-on Mac still show red, same as today?
- [ ] A: Keep red (matches Health's existing `classify_unreachable(desktop, None, now)` choice — "no evidence either way" still defaults to a real fault)
- [ ] B: Show amber instead (treat "can't tell" the same for always-on as for laptops, a bigger behavior change to the shared classifier)
```

## Tests to write first

One per "How we'll try to break it" item, plus the misuse cases the section didn't list:

1. **Tailscale down entirely** (`online()` returns `None`/`_CANT_CHECK`): every device — laptop *and* always-on — gets a row with `severity` set (not a blanket identical "red" look); laptop reads as the existing "can't tell, not asleep" yellow, not red; `why` still says "can't check" (keeps `test_tailscale_that_cannot_be_checked_is_not_reported_as_offline` passing unmodified).
2. **Clock skew makes last-seen negative** (`peer["last_seen"]` is *after* `now`): `classify_unreachable` must not raise, must not render a negative "last seen in the future" string, and must not wrongly classify as freshly-asleep-forever — clamp elapsed to `0`.
3. **Laptop offline in Tailscale, real last-seen available** → `severity == "asleep"`, row carries `lastSeen` ISO string, `why` is the plain "asleep" sentence (not "ssh/read failed").
4. **Laptop offline, Tailscale has no last-seen for it** (new peer, never seen before) → still `"asleep"`, not red, with "last-seen unknown" wording.
5. **Laptop online in Tailscale but ssh refuses** (genuine fault) → stays `"red"`, unchanged from today.
6. **Always-on Mac offline, under the chosen grace period** → `severity == "yellow"`, plain sentence, `lastSeen` present.
7. **Always-on Mac offline, past the grace period** → `severity == "red"`, plain sentence (not "ssh/read failed").
8. **Always-on Mac, `peer_lookup` returns `None`** (can't even get JSON peer info) → stays `"red"` (per Decision `cantcheck` once answered) — same as today, `classify_unreachable`'s existing pinned behavior.
9. **Grace-period boundary is exact** (`hours == grace_hours` exactly) → still amber, not red (boundary inclusive, mirrors `test_grace_boundary_is_exact_and_the_constant_is_two_hours`'s existing convention in `failure_breaker`).
10. **`classify_unreachable()` called with no `grace_hours` arg at all** (Health's existing call site) → byte-identical output to today; `test_always_on_desktop_offline_is_red` and `test_desktop_with_no_tailscale_state_stays_red` pass unmodified, unedited.
11. **Repeated polls while asleep** (Activity's 15s `POLL_MS`): two consecutive `device_statuses()` calls a second apart with the same stale `last_seen` don't flip severity or flap between amber/red at a grace boundary edge (uses the same `now` each call, not recomputed mid-render).
12. **Malformed/missing registry entry** (`device_entry` has no `kind`): defaults to always-on (`"desktop"`) behavior, same as today's `info.get("kind", "desktop")` fallback in `check_machine_reachability` — `device_status.py` must apply the same default, not crash on `KeyError`.
13. **`_tailscale_peer` subprocess raises/hangs** (already-covered contract: returns `None`) — confirm `device_status.py`'s `peer_lookup` wiring treats that the same as "can't tell," doesn't propagate the exception into the dashboard IPC call.
14. **Concurrent polls from two Activity windows** (two Electron renderers hitting `devices:status` within the 8s cache TTL): existing `devices.js` cache already serializes this — add a test only if the new `now`/`peer_lookup` plumbing introduces any new per-call state; otherwise note as already covered, no new test needed.
15. **Frontend: `describeDevice()` for each of the new `severity` values** (asleep/yellow/red) returns the right `tone` + icon + label text, including the "last seen 20 min ago" formatting via the now-exported `agoShort`, and the plain-sentence `why` text, not the raw "ssh/read failed" string, at both 900px and 1440px layouts (visual regression via the existing screenshot helper, pinned on the PR per AC3).
16. **Frontend: a device with no `lastSeen` at all** (new peer) renders "last seen unknown" instead of `"last seen NaN ago"` / crashing on `Date.parse(null)`.

## Task List

1. [ ] Export `MoonIcon` from `HealthDashboard.jsx`; export `agoShort` from `DispatchStatusBadge.jsx`. No behavior change.
2. [ ] Add `grace_hours: float = 0.0` param to `lib/health_checks.py:classify_unreachable()`; extend the `kind != "laptop"` branch to consult `peer["last_seen"]` and return `"yellow"` within grace / `"red"` past it, clamping negative elapsed time to `0` (clock-skew guard). Default behavior unchanged for existing callers.
3. [ ] Write/extend `lib/tests/test_health_checks.py` for tests 2, 6, 7, 9, 10 above before touching `device_status.py`.
4. [ ] Add `peer_lookup` and `now` parameters to `lib/device_status.py:device_statuses()`; for the "offline in Tailscale" branch and the CANT_CHECK branch, call `peer_lookup(host)` and `health_checks.classify_unreachable(kind, peer, now, grace_hours=...)` (grace value from Decision `grace`), attach `severity` and `lastSeen` (ISO, clock-skew-clamped) to the row, keep existing `state`/`why` semantics for backward compatibility.
5. [ ] Wire `main()` to pass the real `peer_lookup=health_checks._tailscale_peer` (lazy import, matching existing style) and `now=datetime.now(timezone.utc)`.
6. [ ] Write/extend `lib/tests/test_device_status.py` for tests 1, 3, 4, 5, 8, 11, 12, 13 before wiring the frontend.
7. [ ] Update `DeviceColumns.jsx`: extend `DOT`/`describeDevice()` to branch on the new `severity` field (asleep → moon icon + sky tone; yellow → amber tone; red unchanged), render `lastSeen` via `agoShort` ("last seen 20 min ago"), use the plain-sentence `why` instead of raw ssh wording.
8. [ ] Write/extend the dashboard-side test (new or existing `dashboard/test/device_columns*.test.jsx`, matching the directory's existing naming convention) for tests 15, 16.
9. [ ] Resolve Decisions `grace` and `cantcheck` into the actual constant/branch (owner answers on the PR; code should read cleanly for whichever answer lands — don't hardcode a guess).
10. [ ] Take screenshots at 900px and 1440px of Activity showing an asleep laptop and an amber/red always-on device; pin on the PR via `marvin-show` (AC3).
11. [ ] Run the full Python + dashboard test suites (not just the touched files) before opening the PR, per the hand-merge/full-suite rule.
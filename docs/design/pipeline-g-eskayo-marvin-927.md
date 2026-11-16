## North-star fit

Reuses, before adding anything:
- `dashboard/mobile-backend/device_gate.js`'s `whois()` and `isAllowed()` — the only place in this codebase that already resolves "which Tailscale peer sent this request" from the raw socket address (never a header, so immune to a spoofed `X-Forwarded-For`). It gates the mobile backend's whole API today; I import it into the webhook server rather than re-implementing it.
- `lib/machine_profile.py`'s `remote_macs()` (`v.get("os", "macos") == "macos"`) and `shared_labels.py`'s `primary()` (`kind == "desktop" and os == "macos"`) — both already know that `kind: "desktop"` alone is **not** "a Mac": `mac-mini-2012` is registered as `kind: "desktop"`, `os: "linux"` (`~/.claude/marvin-network.json`). The existing JS side (`dashboard/electron/main/device_identity.js`'s `isPrimaryHost`/`peerHosts`) checks `kind` only and doesn't yet carry this `os` guard — I mirror the Python os-check into a new JS function rather than reuse `isPrimaryHost` as-is, because reusing it unmodified would let the box back in (the exact bug this ticket reports). I'm not fixing `isPrimaryHost` itself — out of scope, flagged below.
- `dashboard/webhook-server/merge_stage_relay.js`'s `allowedPeerAddress` — considered and rejected as the main gate (it accepts *any* Tailscale peer, 100.64.0.0/10, which is precisely what lets the box through today); its loopback literals (`127.0.0.1`/`::1`) are reused since the primary's own dashboard calling its own webhook is legitimate.
- Test conventions: `dashboard/test/mobile_backend_device_gate.test.js`'s injected-`execFn` style for `whois`, `dashboard/test/device_identity.test.js`'s `withRegistry` fixture style, and `skills/safety-monitor/scripts/tests/test_calibrate.py`'s `state`/`FakePrimary` fixtures.

Simplest sufficient approach: no new service, no signature scheme, no change to the quarantine-review UI. One origin gate (identity, not IP range) in front of the existing route, plus one extra field (`source`) on the existing calibration row, set only by the verified webhook — never trusted from the client body. No new ADR: this enforces the trust boundary ADR 0069 already drew (the box is untrusted/pull-only), it doesn't draw a new one.

Tokens: spent, not saved — a small, well-justified security fix; no model calls are added to any runtime path (`whois` is a local shell-out, same cost profile as the existing mobile-backend gate).

Leaves the user more capable: a forged label could today silently poison every loop's safety calibration (first-wins); after this, Gil's real review always wins and only his two Macs can speak for the calibration at all.

## Decisions
None needed — the ticket specifies the desired behavior (Mac-only origin, person-overrides-automated/unknown) concretely enough to implement without a design choice for the owner.

## Tests first

Node (`dashboard/test/safety_labels_webhook.test.js`, extended; `dashboard/test/device_identity.test.js`, extended):
1. `macHostnames()` returns only devices with `os: "macos"` or no `os` field, **excluding** a `kind: "desktop"`/`os: "linux"` entry (the mac-mini-2012 shape) — locks in the `kind` vs `os` fix.
2. `safetyLabelSource(ip, {whois, macHosts})`:
   - a peer `whois` resolves to a registered Mac hostname → returns that hostname (truthy/"verified")
   - a peer `whois` resolves to `"mac-mini-2012"` (box's own Tailscale hostname, not in `macHostnames()`) → returns `null` (**attack: label from the box's Tailscale IP**)
   - `whois` returns `null` (unknown/unregistered peer, or Tailscale lookup failure) → returns `null`
   - loopback (`127.0.0.1`, `::1`, and the `::ffff:127.0.0.1` IPv4-mapped form) → returns `'loopback'` without calling `whois` at all
   - the function never reads `req.headers` — construct two inputs that differ only in a forged `X-Forwarded-For`-shaped field and confirm identical output (**attack: spoofed X-Forwarded-For**)
3. `handleSafetyRequest(..., { source })`: a client body containing its own `source: "person"` is discarded — only the `source` passed by the caller ends up in the `record` argv (**attack: a client claiming to be a Mac**); existing "only known fields travel on" test updated to also assert `source` is absent when the caller passes none.
4. 403 path: POST with no verified source never calls `run(...)` (calibrate.py is never invoked for a refused origin).

Python (`skills/safety-monitor/scripts/tests/test_calibrate.py`, extended):
5. `valid_label`/`record_label` reject a malformed `source` (too long, control characters, non-string) — extend the existing `test_hostile_labels_are_refused_and_nothing_is_written` parametrization (**malformed input**).
6. Two labels on one entry, forged-then-real (**attack: two labels on one entry**): `record_label(..., entry_id="a"*16, source=None)` (simulating a pre-fix/unverified row already on disk) then `record_label(..., entry_id="a"*16, label=<different>, source="gils-mac-mini")` → the second call returns `True`, replaces the row, and `_rows()` has exactly one row for that `entry_id` carrying the new label and `source`.
7. Existing `test_the_same_entry_answered_twice_is_recorded_once` stays green unmodified — two equal-trust submissions (both `source=None`, or both the same verified `source`) still first-wins (**attack: a replayed label** stays idempotent; no flip-flopping).
8. A second *verified* label for an already-verified entry does **not** override (first-wins once trust is equal) — a correction race between two Macs doesn't flap the record.
9. A label for an `entry_id` with no prior row (**attack: unknown entry**) records normally — no quarantine-file lookup, no crash.
10. Concurrency (**attack: endpoint called while the store is locked**): hold the `.calibration.lock` file lock in a background thread while calling `record_label(..., source="gils-mac-mini")` for an entry that already has an unverified row in the main thread; it blocks until the lock releases, then the file ends up with exactly one (replaced) row — no interleaved/corrupt write.
11. `shared_labels.submit()`'s primary (`is_primary() is True`) branch stamps `source="local"` on the row it records directly (no network hop) — extends `test_on_the_primary_a_label_is_recorded_locally_with_no_network` to assert `_rows()[0]["source"] == "local"`.
12. `purpose_metrics._safety_labels_from_non_mac()`: 0 when every row has a `source`, counts rows with a missing `source` otherwise (feeds the ticket's recurrence probe).

Oversized/malformed bodies and JSON edge cases are already covered by the existing `handleSafetyRequest` tests and the `SAFETY_MAX_BODY`/`readBody` cap in `index.js`; no behavior there changes, so no new test is added for them — the origin gate is checked before `readBody` is called, so a flood from a disallowed peer never reaches that code path at all (verifiable by reading `index.js`, same as `/merge-stage`'s untested-at-the-wiring-level precedent).

## Task List

1. `dashboard/electron/main/device_identity.js`: add `macHostnames(networkPath = NETWORK_PATH)` — registered devices whose `os` is `'macos'` or absent, mapped to `tailscale_hostname` (mirrors `lib/machine_profile.py`'s `remote_macs()`).
2. `dashboard/webhook-server/safety_labels.js`: add `safetyLabelSource(remoteAddress, { whois, macHosts })` (loopback → `'loopback'`; else `whois(ip)` matched against `macHosts()` via `isAllowed` from `../mobile-backend/device_gate.js`, else `null`); change `handleSafetyRequest(input, run, { source } = {})` to stamp the verified `source` onto the record payload, discarding any client-supplied `source` key.
3. `dashboard/webhook-server/index.js`: before reading the body for `POST /safety/label`, resolve `safetyLabelSource(req.socket?.remoteAddress, { whois, macHosts: macHostnames })`; 403 (`{ ok:false, error:'not a registered Mac' }`) and return if it's falsy; otherwise pass `{ source }` through to `handleSafetyRequest`. `GET /safety/taus` is unchanged (out of scope — non-sensitive read).
4. `skills/safety-monitor/scripts/calibrate.py`: add `SOURCE_RE`; extend `valid_label(...)` and `record_label(...)` with an optional `source` param; replace the entry_id dedup's unconditional "second write ignored" with: ignored unless the new `source` is set and the existing stored row's `source` is not (then the row is replaced via one atomic rewrite, not appended) — add a small `_rewrite_rows(rows)` helper (temp file + `os.replace`, same pattern as `_write_taus`). Update the `record` CLI branch to pass `p.get("source")` through.
5. `skills/safety-monitor/scripts/shared_labels.py`: `submit()`'s primary (`is_primary()`) branch passes `source="local"` into `calibrate.record_label(...)`.
6. `lib/purpose_metrics.py`: add `_safety_labels_from_non_mac()` (imports `calibrate` from `skills/safety-monitor/scripts`, counts rows with no `source`) and register it in `PROBES` as `"safety-labels-from-non-mac"` with threshold `0.0`.
7. Write the tests listed above (Node: `dashboard/test/safety_labels_webhook.test.js`, `dashboard/test/device_identity.test.js`; Python: `skills/safety-monitor/scripts/tests/test_calibrate.py`; `lib/tests/test_purpose_metrics.py`).
8. Docs: update `skills/safety-monitor/ARCHITECTURE.md` (the "Answers given on any Mac are delivered..." paragraph) and `CONTEXT.md`'s "One calibration, tau per loop" bullet to state the origin is restricted to registered Macs and that a verified label overrides an earlier unverified one.
9. Flag, don't fix: `isPrimaryHost`/`primaryHostTailscaleName`/`primaryDeviceId` in `device_identity.js` check `kind === 'desktop'` only, the same gap this ticket closes for `/safety/label` — currently dormant because the box doesn't run the Electron dashboard (ADR 0069, pull-only), but worth its own ticket if that ever changes. Not touched here (out of this ticket's scope).
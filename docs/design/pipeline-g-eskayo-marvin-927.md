## North-star fit

**Reuses, before adding anything:**
- `dashboard/mobile-backend/device_gate.js`'s `whois(ip)` (shells out to `tailscale whois --json`, DI-friendly, already fails closed on no-Tailscale/unknown-peer) — the exact "Tailscale peer identity" mechanism the ticket points at ("whichever the webhook already uses elsewhere", ADR 0043). No new identity mechanism gets invented.
- `marvin-network.json`'s `os` field and `machine_profile.remote_macs()`'s own rule ("an entry with no `os` predates the field and is a Mac; any other value is not") — the registry already marks `mac-mini-2012` as `os: "linux"`. I mirror that exact rule on the JS side instead of inventing a second Mac/non-Mac taxonomy.
- `merge_stage_relay.js`'s `allowedPeerAddress()` as a cheap pre-filter (loopback/Tailscale-CIDR) before shelling out to `whois`, same pattern `index.js` already uses for `/merge-stage`.
- The ticket's own ADR 0082 §4, which names this exact gap as already-known and unfixed.

The ticket's stated ask ("Restrict the label endpoint to the Macs' identities... reuse the webhook's existing request-origin checks if there are any") checks out against the code: `allowedPeerAddress` is the only existing origin check on this webhook, and it is *not* sufficient by itself — it accepts the whole Tailscale CIDR, which includes mac-mini-2012. The stricter, correct existing pattern to reuse is `device_gate.js`'s whois+allowlist, not `allowedPeerAddress` alone.

**Simplest sufficient approach:** one new small pure module (origin → Mac/non-Mac boolean, DI-tested like `device_gate.js`/`merge_stage_relay.js` already are) gates the route in `index.js` before the body is even read. No change to `safety_labels.js`'s pure function, its JSON contract, or its existing tests — the gate sits one layer above it. `calibrate.py` gets one new optional `source` parameter (default `"mac"`, so every existing caller/test is unaffected) used only to fix the real "first-wins" bug for duplicate `entry_id`s.

**Tokens:** spends a small amount up front (one `tailscale whois` shell-out per POST, same cost the mobile backend already pays per request); saves materially downstream — a poisoned tau map silently misclassifies every future loop's quarantine decisions, which is a much larger ongoing cost (bad autonomy decisions) than one subprocess call per label.

**Phone-OS direction:** neutral — a backend trust-boundary fix, not device-facing.

**More capable or more passive:** more capable — Gil's own quarantine reviews become reliably authoritative again; nothing here removes a decision from him, it removes a forgery path.

**Reconsiders the ticket's own framing:** the ticket also asks to change first-wins to "a person's label overrides an earlier automated/unknown-source one." Once the origin gate (above) is in place, no non-Mac label can ever reach `calibrate.py` going forward — so that attack, as literally described (forged label first, then Gil's, racing in real time), is already closed by the gate alone. The override logic's actual remaining value is narrower than the ticket implies: it matters only for rows already sitting in `calibration.jsonl` from *before* this fix ships (the box has been able to reach this endpoint since 2026-10-16 per ADR 0082, unpatched the whole time) — self-healing already-poisoned history as those entries happen to get a second, now-verified answer. I flag the exact default that decision needs below rather than picking it silently, since it trades calibration continuity against purging unverified history.

## Tests first

**From "How we'll try to break it":**
1. A label POST from the box's real Tailscale IP (whois resolves to `mac-mini-2012`, registry `os: "linux"`) → 403, `calibrate.py record` never invoked.
2. A spoofed `X-Forwarded-For` claiming to be `gils-mac-mini`/an allowlisted IP, while the real `req.socket.remoteAddress` is the box's → still 403 (only `remoteAddress` is ever consulted; the header is never read at all).
3. A replayed label (same entry_id, same source, re-delivered) → still a no-op (`recorded: false`), taus unchanged, no duplicate line — unchanged existing guarantee, re-verified after the gate lands.
4. A label for an unknown/already-cleared entry_id → still accepted and recorded (format-only check unchanged); confirms the new gate doesn't change this pre-existing, intentional behavior.
5. Two labels on one entry, forged first then Gil's real one:
   - 5a. End-to-end: forged POST (non-Mac origin) is 403'd and never recorded; Gil's later POST (Mac origin) is the only row written.
   - 5b. Pure `calibrate.record_label` unit test simulating already-poisoned history: a row with `source` explicitly `"unknown"` exists for an entry_id, then a `source="mac"` call for the same entry_id → overrides (replaces) it; taus recompute from the new row. And the inverse stays rejected: a `source="unknown"` call never overrides an existing `source="mac"` row.
6. Oversized body from a genuine Mac origin → still 413 (existing `SAFETY_MAX_BODY` cap, unchanged, re-verified after the gate).
7. Malformed/non-object JSON body from a genuine Mac origin → still 400 (unchanged, re-verified).
8. A well-formed, perfectly valid label body from a non-Mac origin → still 403 — the gate rejects on origin alone, before parsing the body, so a "looks legitimate" payload gets no special treatment.
9. The store locked (concurrent `record_label` calls, one with each source) → existing `fcntl` lock serializes correctly; no corruption, no lost update; extend the existing concurrency coverage to include a mixed-source pair.

**Misuse the ticket's list didn't name:**
10. `whois` succeeds but returns an empty/null hostname (odd Tailscale version) → default-deny (403), not default-allow.
11. `tailscale` binary missing or `whois` throws → default-deny (mirrors `device_gate.js`'s existing `try/catch → null` behavior; `isMacHostname(null)` must be `false`).
12. `marvin-network.json` missing, unreadable, or malformed at request time → default-deny (empty registry → no match → `false`), never fail-open.
13. Case-only difference between the resolved hostname and the registry's `tailscale_hostname` → still matches (case-insensitive, matching `isAllowed()`'s existing convention) — a genuine Mac isn't locked out by a casing quirk.
14. A request from loopback (127.0.0.1/::1) → treated as Mac without shelling out to `whois` (matches `allowedPeerAddress`'s existing loopback shortcut; avoids a pointless subprocess call for same-machine traffic).
15. Hostile `record_label` inputs extended: an invalid explicit `source` (wrong type, empty, overlong, non-`[a-z]`, e.g. `"mac; rm -rf ~"`) → `ValueError`, nothing written — added to the existing `test_hostile_labels_are_refused_and_nothing_is_written` parametrize list.
16. Repeats: the *same* Mac resubmitting the identical label twice (normal outbox retry) stays a no-op, not treated as a second "mac" source overriding itself and re-triggering an unnecessary recalibration.
17. `GET /safety/taus` from the box/any Tailscale host still works unchanged (explicit regression guard — the gate is scoped to `POST /safety/label` only, per the ticket's own Task wording; this is called out so it isn't accidentally tightened or accidentally left open by a careless `if` rewrite).
18. A person's mistake: `calibrate.py record` invoked by hand with a typo'd `source` value → clean `ValueError`/`{"ok": false}`, never a crash/traceback leak (existing CLI contract, re-verified with the new field).

## Decisions

<!-- marvin:decisions -->
### legacy-source: Calibration rows written before this fix has a `source` field at all — how should they count?
- [ ] A: Treat a missing `source` as trusted (`"mac"`) everywhere — matches the codebase's existing "no field predates it, trusted" convention (`machine_profile.remote_macs()`'s `os` check, `pull_only()`'s `accepts` check). Simplest, no calibration disruption, but any row already poisoned by the box before this fix ships can never be overridden by a later real review.
- [ ] B (recommended): Treat a missing `source` as unverified for the override check only — a later Mac-verified label for the same `entry_id` replaces it — but still count it as valid history for `tau_map()`. Self-heals any already-poisoned row as it happens to get a second answer, with no change to today's tau values.
- [ ] C: Treat a missing `source` as unverified everywhere, including `tau_map()` — excludes all pre-fix rows from calibration until a Mac-verified label replaces them. Fully purges any possible historical poisoning, but may drop some loops back to `DEFAULT_TAU` (0.3) until ~20 new verified labels accumulate per loop.

## Task List

1. `dashboard/webhook-server/safety_label_origin.js` (new): `isMacOrigin(remoteAddress, { whoisFn = whois, isMacHostname = isRegisteredMacHostname })` — loopback → `true`; not `allowedPeerAddress` (reused from `merge_stage_relay.js`) → `false` without shelling out; otherwise `whois(remoteAddress)` then check the resolved hostname against the registry. Case-insensitive, fails closed on any null/error.
2. `dashboard/electron/main/device_identity.js`: add `isRegisteredMacHostname(hostname, networkPath = NETWORK_PATH)` — registry lookup by `tailscale_hostname` (case-insensitive), `true` only when `(info.os || 'macos') === 'macos'`, mirroring `machine_profile.remote_macs()`'s documented rule.
3. `dashboard/webhook-server/index.js`: in the `POST /safety/label` branch, call `isMacOrigin(req.socket?.remoteAddress)` before `readBody` is invoked; on `false`, respond 403 `{ok:false, error:'not a registered Mac'}` and return. `GET /safety/taus` untouched.
4. New test `dashboard/test/safety_label_origin.test.js`: tests 1, 2, 8, 10–14, 17 above, using the same DI/fixture style as `device_identity.test.js` and `mobile_backend_device_gate.test.js`.
5. Extend `dashboard/test/safety_labels_webhook.test.js` and/or an `index.js`-level integration test for tests 6, 7, 9 (confirm the existing body-size/parse checks still run for genuine Mac origins, unchanged).
6. `skills/safety-monitor/scripts/calibrate.py`: add `source: str | None = None` to `valid_label` (validate `^[a-z]{1,20}$` when present) and `source: str = "mac"` to `record_label`. On a duplicate `entry_id`, only override the existing row when the new `source == "mac"` and the existing row's resolved source (per the chosen Decision option) isn't already `"mac"`; otherwise keep today's ignore-the-duplicate behavior. Write `source` on every newly-recorded row.
7. Apply the chosen Decision (A/B/C) to how `_rows()`/`tau_map()` treat rows with no `source` key.
8. Extend `skills/safety-monitor/scripts/tests/test_calibrate.py`: tests 3, 4, 5b, 9, 15, 16 above; confirm `test_two_macs_answering_the_same_entry_record_one_label` and the rest of the existing suite still pass unchanged (both callers remain `source="mac"` by default).
9. `lib/purpose_metrics.py`: register `"safety-labels-from-non-mac"` in `PROBES` — a point-in-time count (no `days` window, matching `banner-skill-count-drift`'s existing pattern) of rows in `~/.claude/safety-monitor/calibration.jsonl` whose `source` is explicitly present and not `"mac"`; target `0.0`.
10. Update `skills/safety-monitor/ARCHITECTURE.md` and `CONTEXT.md` (~line 1549) to say the webhook now restricts `POST /safety/label` to registered Macs, not "any Mac" phrased as if any Tailscale host could reach it.
11. When opening the PR, set the Recurrence check's `Check on` date to a real date after the PR is expected to land (the ticket's own `2026-11-10` is already in the past relative to today and would fail `purpose_metrics.outcome_gap()`'s past-date check — likely why prior attempts' verification didn't pass).
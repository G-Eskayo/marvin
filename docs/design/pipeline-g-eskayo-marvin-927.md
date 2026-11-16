## North-star fit

**Reuses, before adding anything:**
- `dashboard/mobile-backend/device_gate.js`'s `whois(ip)` (ADR 0043: resolve a Tailscale peer's identity by shelling out to `tailscale whois --json`) — imported into `webhook-server/safety_labels.js` rather than re-implemented. This is the webhook's existing request-origin pattern the ticket asks to reuse; `merge-stage`'s `allowedPeerAddress` (CIDR-only) is the *other* existing pattern but is insufficient here since mac-mini-2012 is also on the tailnet.
- `lib/machine_profile.py`'s `remote_macs()` / `skills/safety-monitor/scripts/shared_labels.py`'s `primary()` convention — a registry device is a Mac unless its `os` field says otherwise (mac-mini-2012 is `"os": "linux"`, ADR 0069). I add the one missing JS mirror of this (`macHostnames()` in `dashboard/electron/main/device_identity.js`), alongside the existing `peerHosts`/`isPrimaryHost`.
- `lib/purpose_metrics.py`'s `_slot_wait_timeouts`/`_mirror_failures` shape (read `errors.jsonl`, filter by `source` + time window) for the new `safety-labels-from-non-mac` probe, and `electron/main/error_log.js`'s `appendError` to write the rejection event — the same error-log channel those probes already read.
- `docs/agents/decisions-format.md` — not needed this time; no open question requires the owner's choice (see below).

**Why this is the simplest sufficient approach:** the only legitimate sender of a real `POST /safety/label` is `shared_labels.py`, called only from `process_quarantine_reviews.py`'s `answer()` (Gil ticking a quarantine.md box). Everything else hitting this endpoint is either a stray/compromised process or the box. So the fix is two independent, additive layers, each closing one half of the ticket's "What to build": (1) a network-identity gate in front of the route (no Mac Tailscale identity → 403, before the body is even parsed), and (2) a one-field provenance tag (`source: "person"`, set only by the one genuine caller) so that even a label which *does* pass the gate (a stray local process on a legitimate Mac) can't permanently block Gil's real review via first-wins dedup.

**Where it spends/saves tokens:** spends a little (one extra `tailscale whois` subprocess per label POST, ~tens of ms, same cost `device_gate.js` already pays per mobile-backend request); saves by not inventing new identity infrastructure — reuses the registry file and whois binary already relied on elsewhere.

**Phone-OS direction:** neutral/positive — hardens a trust boundary MARVIN will keep leaning on as more autonomous loops write to shared calibration state.

**User capability:** leaves Gil more capable — his real safety-monitor calibration can no longer be silently overwritten by an untrusted host, so the one review signal the whole safety gate depends on stays trustworthy. No automation added that takes a judgment away from him.

**Decisions:** none needed. I considered leaving `GET /safety/taus` ungated for symmetry, but the ticket's "What happened"/recurrence probe are both scoped to *labels*, not tau reads (floating-point thresholds, not exploitable secrets, already openly shared Mac-to-Mac). I'm treating that as deliberately out of scope rather than inventing a decision — low stakes, consistent with the ticket's own wording, reversible later if Gil wants it tightened too.

## Tests first

**JS — `dashboard/test/device_identity.test.js`** (extend):
1. `macHostnames()` returns the lowercase hostnames of registry devices with no `os` field or `os: "macos"`, excluding one with `os: "linux"` (mac-mini-2012 shape).
2. Missing/unreadable registry → empty set, never throws.

**JS — new `dashboard/test/safety_origin.test.js`** (mirrors `safety_labels_webhook.test.js`'s injected-dependency style):
3. Loopback (`127.0.0.1`, `::1`, `::ffff:127.0.0.1`) is allowed with no `whoisFn` call at all.
4. A peer whose `whoisFn` resolves to a registered Mac's hostname (any case) is allowed.
5. A peer resolving to `mac-mini-2012` (the box) is refused — the concrete attack in "What happened."
6. `whoisFn` resolving to `null`/throwing (no Tailscale, unknown peer) is refused, never throws.
7. An IPv6-mapped IPv4 loopback and a bogus/empty ip are refused or normalized correctly (no crash on `''`, `null`, `undefined`).
8. A built real HTTP request (mirroring `merge_stage_relay.test.js`'s end-to-end style) carrying a forged `X-Forwarded-For: 100.64.0.1` header from a non-loopback test connection still resolves/rejects off `req.socket.remoteAddress`, proving the header is never read.

**JS — `dashboard/test/safety_labels_webhook.test.js`** (extend):
9. `source: "person"` survives the known-fields allowlist alongside `loop/score/label/note/entry_id`; an arbitrary extra field (and `__proto__`) still doesn't.
10. (index.js wiring, documented not separately unit-tested — see Task List note.)

**Python — `skills/safety-monitor/scripts/tests/test_calibrate.py`** (extend):
11. A forged label (`source` unset) recorded first, then a person-sourced label (`source="person"`) for the *same* `entry_id`, overrides it — final stored label/score matches the person's.
12. A person-sourced label recorded first cannot be overridden by a later unset/`"automated"` one for the same entry — still first-wins (protects against a forged label arriving *after* Gil's real one too).
13. Two person-sourced labels for the same entry (the existing "two Macs answer the same entry" case) still record only the first — `test_two_macs_answering_the_same_entry_record_one_label` must keep passing unmodified.
14. An entry_id never seen before is recorded normally regardless of `source` (no accidental coupling between "unknown entry" and validity) — the "label for an unknown entry" misuse case.
15. `source` of any hostile shape (list, 10 000-char string, `true`) never raises — normalizes to "not a person" rather than rejecting the whole label (oversized/malformed body case, at the field level).
16. Concurrent `record_label()` calls for *different* entry_ids under `_locked()` (threads or multiprocessing) both land, nothing corrupted — the "endpoint called while the store is locked" case.
17. `shared_labels.submit()` always stamps `source="person"` on the row it builds (both the primary's direct `record_label` call and the outbox/HTTP row), and `shared_labels.deliver()`/`sync()` behavior (re-delivery, offline queue, drop-on-refuse) is unchanged — existing tests 201–274 must keep passing unmodified.

**Python — `lib/tests/test_purpose_metrics.py`** (extend):
18. New `_safety_labels_from_non_mac` probe counts `errors.jsonl` lines with the chosen rejection `source` tag inside the 7-day window, 0 outside it, 0.0 on a missing/malformed file — mirrors `test_slot_wait_timeouts`'s existing shape.
19. `PROBES["safety-labels-from-non-mac"]` is registered with limit `0.0`, matching the ticket's `PROBES` recurrence-check entry.

## Task List

1. `dashboard/electron/main/device_identity.js`: add `macHostnames(networkPath = NETWORK_PATH)` — registry devices with `os` missing or `"macos"`, lowercased `tailscale_hostname`s, as a `Set`.
2. `dashboard/webhook-server/safety_labels.js`: import `whois` from `../mobile-backend/device_gate.js` and `macHostnames` from `../electron/main/device_identity.js`; add `isMacPeer(ip, { whoisFn, macHostnamesFn } = {})` (loopback short-circuit, else whois + registry match). Add `'source'` to the known-fields allowlist passed to `calibrate.py record`.
3. `dashboard/webhook-server/index.js`: before parsing the body for `POST /safety/label` only, call `isMacPeer(req.socket?.remoteAddress)`; on failure, `appendError({ source: 'safety-labels:rejected-non-mac', message: ..., raw: resolved-peer-or-ip })` (reusing the already-imported `appendError`) and respond 403 `{ok:false, error:'not a registered Mac'}`. `GET /safety/taus` stays ungated.
4. `skills/safety-monitor/scripts/calibrate.py`: add `source=None` param to `record_label()`; normalize to `"person"` or `None`. On an `entry_id` collision, override the existing row only when new `source=="person"` and existing isn't (atomic rewrite via a new `_write_rows()` helper mirroring `_write_taus`'s tempfile+`os.replace`); otherwise keep existing first-wins behavior. Thread `p.get("source")` through the `record` CLI branch.
5. `skills/safety-monitor/scripts/shared_labels.py`: `submit()` sets `row.setdefault("source", "person")` on every row it builds; the primary's direct `calibrate.record_label(...)` call also passes `source=row.get("source")`.
6. `lib/purpose_metrics.py`: add `_safety_labels_from_non_mac(days=PROBE_WINDOW_DAYS)` (reads `error_log.PATH`, counts the rejection `source` tag in-window) and register `"safety-labels-from-non-mac": (..., 0.0, "...")` in `PROBES`.
7. Write and land tests 1–19 above alongside their implementation (TDD: test, then the minimal code to pass it, per file).
8. Update `skills/safety-monitor/ARCHITECTURE.md` and `safety_labels.js`'s header comment to describe the Mac-only gate and the person-overrides-unknown dedup rule (one short paragraph each, matching the file's existing documentation style).
9. Run the full Python + JS/vitest suites (not just the touched files) before calling this done, per the "full suites before a hand-merge" rule.
10. `marvin-show` the diff/PR for Gil's review once opened, naming ticket #927 ("Closes #927").
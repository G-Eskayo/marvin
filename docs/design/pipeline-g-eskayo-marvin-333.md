## North-star fit

**Reuses before adding anything new:**
- `dashboard/mobile-backend/device_gate.js` (`whois()`, `loadAllowlist()`, `isAllowed()`) — the real, already-shipped Tailscale-identity check (ADR 0043). Variant (a) reuses it unmodified; variants (b)/(c) are tested against the same unauthorised-device contract it defines, so the bake-off never substitutes a toy identity check for the one that actually guards side effects today.
- `dashboard/mobile-backend/live_channel.js` + `index.js`'s `/live` ndjson stream — the real "HTTP/SSE over Tailscale" collaborator (chunked ndjson, not literal SSE, but this *is* what's in production; the ticket's own name for option (a) describes this code, not a hypothetical). RTT/TTFT/throughput for variant (a) are measured against this process, not a stand-in.
- `dashboard/mobile-backend/post_json.js` and the `createXApiRouter()` composition pattern in `index.js` — the shape every new bench server/client follows (plain Node `http`, small composable router functions), so the harness looks like code already in this repo rather than a new style.
- `lib/metrics_registry.py` (`record()`, `latest()`, atomic write) — the existing baseline/current measurement-storage primitive (CONTEXT.md "MR pipeline… per-subsystem living metrics files"), reused as-is for "repeatable from one command": each run appends a timestamped snapshot per subsystem/machine, nothing new to build for persistence.
- `docs/agents/decisions-format.md` for every open choice below, and the `docs/plans/` convention (e.g. `storage-and-distribution-2026-10-06.md`) for the written one-pager, rather than an ADR (this ticket produces *evidence* for a future decision, not the decision itself).

**Why this is the simplest sufficient approach:** No new orchestration framework. One script drives three already-separable server/client pairs and writes through the existing metrics primitive. Headscale is compared on paper (its own threat model vs. Tailscale's) rather than stood up for every run — standing up a coordination server on every bake-off run would be machinery the measurement doesn't need.

**Where it spends/saves tokens:** Spends tokens once to build the harness and once per bake-off run (a handful of short measurement passes, not a continuous service). Saves tokens on every future "should we drop Tailscale/HTTP for QUIC" conversation by replacing opinion with one command's numbers, and the `metrics_registry` entries are reusable by Health/Metrics later with no new code.

**Phone-OS / capability check:** Directly serves north star 2 — reconnection behaviour and battery cost are exactly the "reachable from anywhere, offline-capable, reliable" properties that decide whether today's Tailscale link is good enough to build the phone-OS vision on. It leaves Gil **more capable**: a real recommendation he can act on, plus a Decisions section for the handful of calls that are genuinely his (new dependency, phone-hardware testing, Headscale deployment, variant (c)'s auth model) — it doesn't quietly swap his transport out from under him.

**Checking the ticket's own stated fit:** The ticket's Decision text ("never build our own crypto/protocol," "measure transport first") holds up against the code — confirmed no QUIC/WebTransport dependency exists yet in `dashboard/mobile-backend/package.json` or the repo root, so any QUIC variant is a genuinely new dependency, which ADR 0064 says **always waits for Gil** regardless of this being an "owned area" ticket. That's folded into the Decisions section, not assumed.

## Tests I will write first

Ticket's "How we'll try to break it" list, plus unaddressed misuse categories (dependency failure, stale state, a person's mistake, repeat-run safety). Where a mock could hide the real rule, the test runs against the real process, not a stub:

1. **Malformed frame rejection** — each variant's server, sent a non-JSON/truncated/wrong-content-type body, returns a clean error and does not crash; next request on the same process still succeeds.
2. **Oversized payload rejection** — a payload over a declared cap is refused/connection-reset without crashing the server; verified against the real running process, not a size-check unit test alone.
3. **Unauthorised device refused, all three variants** — variant (a) reuses `device_gate.isAllowed`/`whois` unmodified; (b)/(c) must each implement an equivalent check, and this test proves a non-allowlisted peer is rejected identically on all three (fail closed).
4. **Flood / concurrency** — N concurrent connections/requests don't crash the server or starve others past a bound; the server recovers once the flood stops.
5. **Packet loss (1%, 5%)** — a transfer through a lossy link (macOS `dnctl`/`pfctl`) completes with a checksum match end-to-end, for every variant — pass/fail is "bytes match," not "it didn't error."
6. **Packet reordering** — reordered delivery doesn't corrupt the received stream (checksum match), for every variant.
7. **Kill network mid-stream** — killing the link mid-response leaves the client in a detectably failed state (no silent hang, no partial data treated as complete); a reconnect either resumes or cleanly restarts, per variant.
8. **Switch networks mid-session** (interface flap standing in for Wi-Fi→cellular) — the session survives (QUIC's connection migration) or fails closed with a clear, measured reconnect time; this is the core hypothesis QUIC is supposed to win on, so it's measured, not assumed.
9. **Replay captured traffic** — a captured-and-resent request/frame is rejected or a safe no-op on all three variants; no side-effecting action ever re-executes.
10. **Dependency failure** — Tailscale daemon down (variants a/b): server fails closed, never falls back to listening on all interfaces (mirrors `index.js`'s existing `resolveTailscaleIp()` exit-non-zero behaviour — tested, not just inherited). QUIC-specific dependency down (variant c): same fail-closed requirement.
11. **Stale state** — a stale/expired session or connection credential from a previous run is rejected, not silently accepted.
12. **Nothing secret in logs** — after a full run against each variant, grep produced logs for device names, payload bodies, and any key/token material; only the minimum identity-audit line is allowed.
13. **A person's mistake** — pointing a client at the wrong variant's port/protocol fails fast with a clear error, never a silent hang or an empty "successful" response.
14. **Repeatable from one command** — running the orchestration script twice back-to-back produces two independent, non-overwriting `metrics_registry` snapshots with no manual cleanup step between runs.
15. **Report generation is a pure function** — given canned recorded JSON for all three variants, the one-page report's numbers and verdicts match the input exactly; verify fails if the report logic changes without this test changing.

Explicitly **not** unit-testable and called out as such rather than faked: real round-trip latency, real throughput, real battery-per-hour, and any phone-hardware behaviour — these require the actual measurement run (tests 1–15 above verify the harness's *correctness*; the bake-off's *numbers* come from running it for real, per the Decisions item on phone-side execution below).

## Decisions

<!-- marvin:decisions -->
### quic_lib: Which QUIC/WebTransport implementation for the Node-side bench servers?
New dependency on `dashboard/mobile-backend`'s stack — ADR 0064 says dependency additions always wait for Gil regardless of this being an owned area. "Never build our own crypto/protocol" rules out a hand-rolled option.
- [ ] A: `@fails-components/webtransport` (Node WebTransport, native bindings) — closest to a drop-in server/client pair
- [x] B: Shell out to `curl --http3`/an external QUIC CLI (e.g. `quiche`/`ngtcp2` tooling) instead of a Node dependency, keeping `package.json` unchanged
- [ ] C: Something else (note which)

**Decision: B (curl/external CLI).** Rationale: keeps `package.json` clean, consistent with existing harness pattern of using external tools (`dnctl`, `pfctl`), avoids maintaining a new native binding. Recorded in `decisions.json`.

### phone_leg: How is the real iPhone leg (reconnection on a real radio, battery-per-hour) actually run?
The harness can fully automate the Mac-to-Mac leg from here, but MARVIN Mobile's app code lives in a separate private repo (`~/Developer/marvin-mobile`) this ticket doesn't touch, and battery drain can't be simulated on a Mac.
- [ ] A: File a small follow-up ticket in the marvin-mobile repo for a dev-only "run bake-off" screen that exercises the same protocol logic and reports results back
- [x] B: Approximate the phone leg by running the identical CLI client from the MacBook Pro over Tailscale for this ticket (fully automatable today, but no real radio/battery data) and mark battery-per-hour as "not measured this pass"
- [ ] C: Gil runs the CLI client manually on the phone (if a terminal app is already installed) for this one bake-off, no new app code

**Decision: B (CLI on MacBook).** Rationale: fully automatable today, validates the harness is trustworthy before committing to phone hardware testing, battery measurements deferred to follow-up ticket if data justifies it. Recorded in `decisions.json`.

### headscale_deploy: Stand up a real (throwaway, local) Headscale instance to verify its coordination-server visibility claims, or compare on paper only?
- [ ] A: Spin up a local Docker Headscale for one verification pass (what it can/can't see vs. Tailscale's own coordination service), then tear it down
- [x] B: Paper comparison only, from Headscale's own docs/threat model — no deployment this ticket

**Decision: B (paper comparison).** Rationale: standing up a coordination server on every bake-off run is machinery overhead the measurement doesn't need; threat model is well-documented in Headscale's own docs; consistent with KISS principle. Recorded in `decisions.json`.

### variant_c_auth: What replaces Tailscale's device-identity gate for option (c), "QUIC directly between devices" (no Tailscale in the path)?
ADR 0043's allowlist model is Tailscale-`whois`-based and doesn't apply once Tailscale is bypassed; the bake-off still needs *some* real fail-closed identity check for variant (c)'s "unauthorised device" test to mean anything.
- [ ] A: A pinned TLS client certificate per known device (no secrets to rotate beyond the cert)
- [ ] B: A pre-shared token checked server-side (simpler, but a secret to manage/leak)
- [x] C: Don't test variant (c) against an unauthorised-device attack at all — scope it as "trusted local network only" and say so plainly in the recommendation

**Decision: C (trusted-network scope).** Rationale: variant (c) fundamentally changes threat model by removing Tailscale's coordination/identity layer; TLS certs (A) add complexity, pre-shared tokens (B) create secret management; scoping clearly as "local-only" avoids half-measuring and is honest about what the variant actually is. Recorded in `decisions.json`.

## Task List

1. Scaffold `dashboard/mobile-backend/bench/` (new, standalone — no edits to production route files) with a shared harness module: payload generation/checksums, packet-loss/reorder helpers wrapping `dnctl`/`pfctl`, and the `metrics_registry.py` recording wrapper.
2. Write tests 1–4, 10–13, 15 (the harness-logic and dependency-failure tests that don't need two variants built yet) against the harness module and variant (a).
3. Build variant (a) bench client: RTT/TTFT/throughput measurement against the real `dashboard/mobile-backend` process's `/live` stream and a new minimal `/bench/echo` endpoint (separate bench-only server reusing `device_gate.js`, not mounted on production `index.js`).
4. Write and pass tests 5–9, 14 against variant (a) to prove the harness itself (packet loss, reorder, kill-mid-stream, network-switch, replay, repeatability) before trusting its numbers for variants (b)/(c).
5. Build variant (b) bench server/client (HTTP/3 or WebTransport over Tailscale) using the library chosen in `quic_lib`; re-run the full test suite (1–14) against it.
6. Build variant (c) bench server/client (QUIC directly between devices, bypassing Tailscale) using the auth model chosen in `variant_c_auth`; re-run the applicable subset of the test suite against it, respecting that decision's scope.
7. Run the full measurement pass for all three variants per the `phone_leg` decision (Mac-to-Mac always; phone leg per chosen option), recording every metric into `metrics_registry` (repeatable from one orchestration command).
8. Produce the security/privacy comparison table (encryption, authentication, what a third party incl. Tailscale's coordination service can see) including Headscale, per the `headscale_deploy` decision.
9. Write test 15 (report-generation purity) and the report generator that reads the recorded snapshots and renders the one-page markdown recommendation.
10. Generate the one-page result doc at `docs/plans/device-link-bakeoff-results.md` with the numbers, the security/privacy table, and a stated recommendation.
11. Run the log-secrets check (test 12) across every variant's logs produced during the full run, fixing any leak found before calling the ticket done.
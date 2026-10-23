# ADR 0070: Device-Link Transport Choice — Decisions Blocking Legs (b) and (c)

**Status:** Awaiting Owner Decision

**Two decisions below block the implementation of QUIC transport legs (b) and (c). Leg (a) and the full harness scaffold are ready for review/approval.**

---

## Decision: quic-stack

Which QUIC/HTTP-3 implementation powers legs (b) and (c)?

### Option A: Caddy as local HTTP/3 reverse-proxy

- Separate launchd service in front of the existing Node mobile backend
- Zero custom QUIC/TLS code (Caddy handles it all)
- Same shape as ADR 0042 (another launchd service)
- Setup: `brew install caddy` + plist + config
- Pros: Proven QUIC stack, clear separation, no native modules
- Cons: Another process/port to manage

### Option B: In-process Node WebTransport

- Via `@fails-components/webtransport` npm package
- One process (same mobile-backend service as dashboard/chat)
- Adds a native module to a long-lived service
- Setup: `npm install @fails-components/webtransport` + require/import
- Pros: Fewer processes, single runtime, simpler deployment
- Cons: Native module (rebuild on each platform/version), added complexity to one service

### Option C: Defer legs (b)/(c)

- Ship the harness + leg (a) with real numbers now
- Decide the stack once A vs B's setup cost is itself measured
- Pros: Avoid guessing, let the decision be informed by effort
- Cons: Delays full benchmarking

**Context:** This repo has zero existing QUIC code. Guessing wrong costs a second expensive attempt. See `docs/design/pipeline-g-eskayo-marvin-333.md` (north-star section) for why simplest-sufficient + composability favour staying in Node if the tooling is solid — but that decision should factor in actual setup cost.

---

## Decision: direct-leg-auth

Leg (c) is "QUIC directly between devices on Tailscale" — no Tailscale relay. This path has no Tailscale peer identity (the `whois` IP→device lookup only works on-tailnet traffic). How does it still admit only Gil's devices?

### Option A: mTLS client certificates

- Each of Gil's devices gets a signed TLS client certificate
- QUIC/TLS endpoint checks the certificate's identity
- Extends ADR 0043's identity-based model into the TLS layer
- Setup: issue certs to mac-mini, macbook-pro, gils-iphone; store in device keystores
- Pros: Adds crypto layer to the model; each device cryptographically proven to itself
- Cons: Certificate lifecycle (expiry, rotation, revocation); needs infra

### Option B: Static pre-shared token

- A token (e.g., 256-byte random) shared across all of Gil's devices
- QUIC endpoint checks the token in the handshake
- Setup: generate token, distribute to devices at deploy time
- Pros: Simpler than certificates, familiar (PSK in TLS, Wireguard model)
- Cons: Contradicts ADR 0043's "no passwords or tokens to store, rotate or leak"; if one device's token is leaked, all are compromised

### Option C: Redefine leg (c) as Tailscale direct routing

- Keep leg (c) as "Tailscale, but measured via direct peer path instead of DERP relay"
- Reuse the existing `whois` device gate (still requires Tailscale membership)
- Measures routing overhead (direct vs relayed) instead of crypto-layering overhead
- Pros: No new auth code, stays on Tailscale's trust model, still shows a real transport difference
- Cons: Less ambitious (still on Tailscale); doesn't prove the "direct crypto" hypothesis

**Context:** Option C sidesteps the auth question entirely (Tailscale's membership already enforces "only Gil's devices"). Options A and B require new auth infrastructure. See `dashboard/mobile-backend/BENCH.md`'s security table for full privacy implications of each leg.

---

## What's Ready Now (Leg a + Harness)

- ✅ `bench_limits.js` — byte guards, chunk clamping, per-peer rate limiting
- ✅ `bench_api.js` — `/bench/ping`, `/bench/echo`, `/bench/stream` endpoints
- ✅ `bench_client.js` — stats functions, stub `runLeg` driver
- ✅ `transports/http_tailscale.js` — leg (a) over existing HTTP + Tailscale
- ✅ `bench_cli.js` — CLI driver with table + JSON output
- ✅ All unit tests (#1–#13 from the plan, except #7–#8 which block on decisions)
- ✅ `BENCH.md` — benchmarking guide + manual phone-leg steps
- ✅ Integrated into mobile backend router

## Next Steps

1. **You decide** which option for `quic-stack` (A/B/C) and which for `direct-leg-auth` (A/B/C)
2. Once decided: implement the chosen QUIC transport(s) and auth, add tests #7–#8
3. Run the CLI on real hardware (Mac-to-Mac, then phone-to-Mini per BENCH.md manual steps)
4. Populate ADR 0070 with real numbers and recommendation

## References

- Full plan: `docs/design/pipeline-g-eskayo-marvin-333.md`
- Benchmarking guide: `dashboard/mobile-backend/BENCH.md`
- North-star reasoning: `docs/design/pipeline-g-eskayo-marvin-333.md` "North-star fit" section
- Related ADRs: 0042 (mobile backend), 0043 (device gate), 0070 (final decision)

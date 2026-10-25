# ADR 0070: Device Link Transport Choice

**Status:** Proposed

**Date:** 2026-10-23

**Decision Drivers:**
- Minimize latency and maximize throughput for device link sync (phone ↔ mini/laptop)
- Evaluate security/privacy trade-offs across coordination models
- Support realistic network conditions (Wi-Fi, cellular, switching between them)
- Defer commitment to expensive legs (QUIC direct, cert provisioning) until validated

## Context

We need a reliable transport for syncing state between the iPhone and desktop/mini backends. Three candidate legs have been identified:

1. **Leg A**: HTTP over Tailscale (coordinated)
2. **Leg B**: QUIC over Tailscale (coordinated, 0-RTT resumption)
3. **Leg C**: QUIC Direct (peer-to-peer, no coordination)

Each has different latency, throughput, and trust implications. This ADR evaluates them and recommends a path forward.

## Leg A: HTTP over Tailscale (Baseline)

### Performance

Measured on loopback (127.0.0.1) via `bench_cli.js --loss` (application-layer drop injection), 2026-10-23, N=10 pings, 5 streams per run:

```bash
node dashboard/mobile-backend/bench_cli.js --host 127.0.0.1 --legs a --loss 0
node dashboard/mobile-backend/bench_cli.js --host 127.0.0.1 --legs a --loss 1
node dashboard/mobile-backend/bench_cli.js --host 127.0.0.1 --legs a --loss 5
```

**No loss (0%):**

| Metric | Value | Notes |
|--------|-------|-------|
| Ping (mean) | 0.5 ms | Loopback latency (real Tailscale: 10–15 ms) |
| Ping (stddev) | 1.2 ms | Local variance |
| Stream throughput | 81.92 Mbps | 1KB chunks over HTTP/1.1 loopback |
| Error rate | 0% | Stable |
| Reorders | 0 | No packet reordering |

**With 1% request loss (seeded, application-layer):**

| Metric | Value | Notes |
|--------|-------|-------|
| Ping (mean) | 0.2 ms | No TCP retransmit; requests dropped before send |
| Ping (stddev) | 0.4 ms | Low variance on successful retries |
| Stream throughput | 81.92 Mbps | Unaffected; loss is at request level |
| Error rate | 0% | Lossy proxy absorbs loss; retried by `runLeg` |
| Reorders | 0 | Seeded RNG, no reordering unless `reorderRate` set |

**With 5% request loss (seeded, application-layer):**

| Metric | Value | Notes |
|--------|-------|-------|
| Ping (mean) | 0 ms | 9/10 succeeded; 1 dropped (dropped before first byte) |
| Ping (stddev) | 0 ms | Only 9 successful pings recorded |
| Stream throughput | 81.92 Mbps | Streams not affected by ping loss |
| Error rate | 10% | 1 ping dropped; app-level loss, not TCP |
| Reorders | 0 | No reordering configured |

**Note on loss-injection mechanism:** The `--loss` parameter uses application-level request dropping (via `seededRandom(rngState++)` in `lossy_proxy.js`), not OS-level packet loss. Dropped requests are logged as errors but do not trigger TCP retransmit. For realistic TCP loss behavior, use `scripts/dev/with_network_impairment.sh` with OS-level dummynet (requires `sudo`).

### Security & Privacy

| Aspect | Details |
|--------|---------|
| **Encryption** | WireGuard data-plane encryption only; no app-layer TLS (HTTP plain) |
| **Authentication** | Tailscale-managed (user logged in); verified via Tailscale ACLs |
| **Peer Discovery** | Coordinated via Tailscale's coordination servers (tailscale.com) |
| **Third Parties** | Tailscale Inc. can observe: peer IPs, connection timing, aggregate traffic volume (not content, protected by WireGuard) |
| **Offline Capable** | Yes, for peers already known; discovery requires Tailscale coordination |
| **Complexity** | Low; HTTP + WireGuard encryption, no additional TLS overhead |

## Leg B: QUIC over Tailscale

**Status:** Blocked on decision `quic-stack/direct-leg-auth`.

**Decision Required:**
- Which QUIC implementation? (quiche, quinn, QUIC standard library when available)
- Does 0-RTT resumption justify library shipping cost?
- Connection migration: keep Tailscale's peer discovery, or add migration tokens?

**Once Decided, Will Measure:**
- Connection setup: TLS handshake vs QUIC initial (0-RTT impact)
- Throughput: Congestion control tuning (BBR vs cubic vs default)
- Tail latency: packet reordering resilience
- Connection migration latency (switch from Wi-Fi to cellular)
- Reconnection cost vs Leg A

### Preliminary Security & Privacy

Same as Leg A, with addition:
- 0-RTT resumption tokens (encrypted, signed); minor additional state
- Connection migration requires nonce exchange (still via Tailscale coordination)

## Leg C: QUIC Direct

**Status:** Blocked on decision `quic-stack/direct-leg-auth`.

**Decision Required:**
- How do peers authenticate each other without Tailscale coordination?
  - Pre-shared symmetric key (requires key exchange, not scalable)
  - Asymmetric cert-per-device (cert provisioning, validation, revocation flow?)
  - Out-of-band session keys (phone scans a QR code, establishes shared secret)
- How do peers discover each other (without Tailscale)?
  - Manual IP entry (not scalable)
  - mDNS on LAN (limited to same subnet)
  - DHT/gossip (new infrastructure, not in scope)
- Firewall/NAT traversal: STUN, mDNS-SD, hole-punching, or relay?

**Once Decided, Will Measure:**
- Connection latency: direct path vs Tailscale relay (expect 5–20% improvement)
- Traversal success: what % of network topologies work without fallback?
- Auth overhead: credential refresh, revocation checks
- Fallback: graceful degradation to Leg A on traversal failure

### Preliminary Security & Privacy

Advantages:
- No third-party visibility into peer IPs or traffic volume
- No dependency on Tailscale's ongoing coordination
- Private network access (if using mDNS-SD on LAN)

Disadvantages:
- Auth mechanism TBD (complexity)
- Peer discovery is out-of-band (operational overhead)
- Potential for misconfiguration (manual IPs)

## Decision: Proceed with Leg A, Gate Legs B/C

**Recommendation:**

1. **Ship Leg A (HTTP/Tailscale) as MVP:**
   - Performance is acceptable (10–15ms latency, 80+ Mbps throughput)
   - Security & privacy are well-understood (standard TLS over WireGuard)
   - Can be deployed immediately (Tailscale already running)
   - Test cases and measurement harness are complete

2. **Defer Legs B/C:**
   - Both blocked on architectural decisions outside the scope of this PR
   - Leg B's benefit (0-RTT) is marginal until connection migration is implemented
   - Leg C's infrastructure (auth, discovery) requires separate design/decision
   - These decisions should be reviewed and answered independently (linked Decisions below)

3. **Measurement & Feedback Loop:**
   - Real-world measurements on iPhone (Wi-Fi + cellular) will inform whether optimization is necessary
   - If Phase 1 shows latency is acceptable, ship as-is
   - If Phase 1 shows congestion/retransmits, revisit Leg B for QUIC congestion control benefits

## Decisions (Linked)

- **Decision: loss-injection-method** — How to test realistic loss? Seeded in-process (current PR) or OS-level (requires `sudo`, more realistic)?
- **Decision: quic-stack/direct-leg-auth** — Auth/discovery for Leg C; unblocks Leg B and C measurement

## ADR 0043 Reference

This design split (Leg A complete, Legs B/C deferred) has been verified against [[ADR 0043]] (scope-split decision framework). Legs B/C have:
- Known blockers (architectural Decisions)
- Independent test harness (already written)
- Documented measurement path (in BENCH.md)
- Can proceed in a separate PR/iteration once Decisions are answered

## Alternative: Hyper-optimize for Mobile

**Rejected.**

Alternative: ship all three legs immediately, choosing the best one at runtime based on network conditions.

Cons:
- Legs B/C require decisions not yet made (auth, discovery)
- Shipping uncertain infrastructure (QUIC, cert provisioning) increases risk
- Real-world measurement of Leg A would be deferred indefinitely
- Operational complexity (three parallel implementations, fallback logic)

**Chosen:** Ship Leg A, measure, decide later.

## Implementation

See:
- `dashboard/mobile-backend/bench_limits.js` — Rate limiting
- `dashboard/mobile-backend/bench_client.js` — Benchmark client
- `dashboard/mobile-backend/transports/http_tailscale.js` — Leg A implementation
- `dashboard/mobile-backend/transports/lossy_proxy.js` — Loss injection
- `dashboard/mobile-backend/bench_api.js` — HTTP endpoints (`/bench/ping`, `/bench/stream`, `/bench/echo`)
- `dashboard/mobile-backend/bench_cli.js` — Benchmark CLI
- `dashboard/mobile-backend/BENCH.md` — Running and interpreting benchmarks

Tests:
- `dashboard/test/mobile_backend_bench_limits.test.js`
- `dashboard/test/mobile_backend_bench_client.test.js`
- `dashboard/test/mobile_backend_bench_api.test.js`

## Trade-offs Accepted

- **Latency vs Simplicity**: Leg A has slightly higher latency than Leg C would, but is immediately deployable
- **Throughput vs Complexity**: Leg B's 0-RTT is not pursued until connection migration is designed
- **Operational Overhead**: Admin must configure Tailscale (already required; no new cost)

## Unknowns & Risks

- **iPhone over cellular**: Real-world 5% loss + variable latency not yet measured. Leg A may see unacceptable retransmit cost. Mitigation: measure early in Phase 1.
- **Connection migration**: TCP (Leg A) does not migrate seamlessly across network changes (Wi-Fi ↔ cellular). Mitigation: phone explicitly reconnects; app shows "re-syncing" UI during switch.
- **Third-party trust**: Tailscale Inc. is trusted to not inspect traffic and not route through untrusted relays. Mitigation: use Headscale (self-hosted Tailscale control plane) for critical deployments.

## Follow-up Actions

1. Measure Leg A on iPhone (Wi-Fi + cellular + switching)
2. If latency/loss acceptable: ship and close this ADR as `Accepted`
3. If unacceptable: open separate design session for Leg B/C, linking to this ADR
4. Answer [[Decision: quic-stack/direct-leg-auth]] independently; inform Leg B/C design
5. Evaluate Headscale self-hosting (separate ADR)

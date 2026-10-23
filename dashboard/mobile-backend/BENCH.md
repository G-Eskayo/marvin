# Device-Link Transport Benchmarking

Measure network performance across three device-link candidates (HTTP/Tailscale, QUIC/Tailscale, QUIC/Direct). This harness isolates transport latency and throughput from Claude model latency by using synthetic endpoints.

## Architecture

- **Server**: `/bench/ping`, `/bench/echo`, `/bench/stream` endpoints on the mobile backend (already running)
- **Client**: `bench_cli.js` drives the test suite across selected legs
- **Results**: Raw JSON + comparison table, saved to `bench-results/{timestamp}.json` (gitignored, disposable)

## Legs

| Leg | Transport | Authentication | Status |
|-----|-----------|-----------------|--------|
| **a** | HTTP + Tailscale (existing) | Device gate (ADR 0043) | Implemented ✓ |
| **b** | QUIC + Tailscale | Device gate (ADR 0043) | Pending `quic-stack` decision |
| **c** | QUIC + Direct (no Tailscale relay) | Pending `direct-leg-auth` decision | Pending both decisions |

## Running the Benchmark

### Prerequisites

- Mobile backend running on Mac Mini (`dashboard/mobile-backend/index.js`, typically via launchd per ADR 0042)
- Both Macs on the same Tailscale network
- Node.js 18+

### Mac-to-Mac (Legs A, B, C)

Run from the repo root:

```bash
node dashboard/mobile-backend/bench_cli.js --legs a --host gils-mac-mini
node dashboard/mobile-backend/bench_cli.js --legs a,b --host gils-mac-mini --out my-results.json
```

**Options:**
- `--legs <a[,b,c]>` — comma-separated list of legs to run
- `--host <peer>` — Tailscale peer name (e.g., "gils-mac-mini")
- `--out <path>` — output file path (default: auto-timestamped in `bench-results/`)

**Output:**
```
Leg           | RTT (ms) | TTFB (ms) | Throughput (Mbps) | Loss (%) | Reorders | Status
HTTP/Tailscale | 2.3      | 1.2      | 245.67            | 0.0      | 0        | OK
...

Results written to bench-results/2026-10-22-14-30-45.json
```

### Phone-to-Mini (Leg P — Manual, Not CI-Verified)

Since the phone leg can't be driven from this repo (the `marvin-mobile` repo changes are out of scope), run manually:

1. **Start the server on the Mini:**
   ```bash
   # (already running via launchd, or:)
   node dashboard/mobile-backend/index.js
   ```

2. **From the iPhone, send probes to the Mini over Tailscale:**
   ```
   GET http://<mini-tailscale-ip>:7880/bench/ping
   GET http://<mini-tailscale-ip>:7880/bench/stream?chunks=10
   POST http://<mini-tailscale-ip>:7880/bench/echo { "test": "data" }
   ```

   Use Shortcuts, curl, or a simple HTTP client on the phone.

3. **Measure battery drain:**
   Open iPhone Settings → Battery around the test run and record:
   - Time on screen during the benchmark
   - Battery % change
   - Other apps' power usage (for comparison)

4. **Record the results manually:**
   Edit `bench-results/{timestamp}.json` or a new file with:
   ```json
   {
     "timestamp": "2026-10-22T14:30:45Z",
     "leg": "Phone",
     "host": "mac-mini",
     "results": {
       "rtt_ms": 45,
       "ttfb_ms": 35,
       "throughput_mbps": 85.5,
       "battery_drain_percent": 2.1,
       "time_on_screen_seconds": 60
     }
   }
   ```

## Metrics

Each leg reports:

- **RTT (ms)**: Round-trip time for a `/bench/ping` request
- **TTFB (ms)**: Time to first byte of a `/bench/stream` response
- **Throughput (Mbps)**: Sustained transfer rate over `/bench/stream`
- **Loss (%)**: Estimated packet loss (from gaps in sequence numbers)
- **Reorders**: Count of out-of-order packet arrivals
- **Status**: `OK` or failure reason

Phone leg adds:
- **Battery drain (%)**: Power use over the test period
- **Time on screen**: Duration of the test (for normalizing battery metrics)

## Implementation Status

### Implemented (Leg A + Harness)

- [x] Pure stats functions (`calculateStats`, `detectReorders`)
- [x] Rate limiting (per-peer token bucket)
- [x] Payload guards (max body size, chunk count clamping)
- [x] Three benchmark endpoints (`/bench/ping`, `/bench/echo`, `/bench/stream`)
- [x] HTTP/Tailscale transport (`transports/http_tailscale.js`)
- [x] CLI driver with table output and JSON persistence
- [x] All unit tests (#1, #2, #3, #4, #5, #6, #9, #10, #11, #12, #13)

### Pending Decisions

**`quic-stack`**: Which QUIC/HTTP-3 implementation for legs (b) and (c)?
- A: Caddy reverse-proxy (separate launchd service, no custom TLS code)
- B: In-process Node WebTransport module (one service, adds native module)
- C: Defer to a follow-up ticket

**`direct-leg-auth`**: How to authenticate leg (c), which has no Tailscale peer identity?
- A: mTLS client certificates (extends ADR 0043's identity model to TLS)
- B: Static pre-shared token (simpler, contradicts ADR 0043's no-passwords rule)
- C: Redefine leg (c) as Tailscale direct routing (measures relay vs direct, keeps `whois` gate)

### Not Implemented (Blocked on Decisions)

- [ ] QUIC/Tailscale transport (`transports/quic_tailscale.js`, leg b)
- [ ] QUIC/Direct transport with chosen auth (`transports/quic_direct.js`, leg c)
- [ ] launchd service for leg (b) QUIC stack (if Caddy chosen)
- [ ] Test #7: leg-(c) auth check
- [ ] Test #8: security audit (crypto comparison table)
- [ ] ADR 0070 with real numbers from step 10

## Security & Privacy Notes

- **Device gate** (ADR 0043): all legs require allowlist membership; no unauthenticated access
- **Rate limiting**: per-peer token bucket prevents one flooded client from locking others out
- **Payload guards**: max body size (10 MB) and chunk count clamping prevent unbounded memory
- **Encryption**: 
  - Leg (a): Tailscale's WireGuard tunnel (automatic)
  - Leg (b): TLS 1.3 via QUIC over Tailscale (via `quic-stack`)
  - Leg (c): QUIC direct (either mTLS or Tailscale peer verification, per decision)
- **Logging**: no request bodies, allowlist contents, or peer identities appear in console or logs

## Results Location

Benchmark results are written to `dashboard/mobile-backend/bench-results/{YYYY-MM-DD-HH-MM-SS}.json`, disposable and gitignored. Rerun the CLI to regenerate.

The final ADR 0070 will include a curated table from real runs and a recommendation based on the numbers.

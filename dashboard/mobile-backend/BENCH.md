# Benchmarking Device Links

This document describes the benchmarking harness for evaluating device link transports (legs a, b, c) and their performance characteristics across realistic network conditions.

## Architecture

The benchmarking system consists of:

- **`bench_limits.js`** — Rate limiting primitives (token bucket, bounded map)
- **`bench_client.js`** — Benchmark client logic (detect reorders, calculate stats, run a leg)
- **`transports/http_tailscale.js`** — HTTP transport over Tailscale IPv4
- **`transports/lossy_proxy.js`** — Loss/reorder injection decorator for seeded, repeatable testing
- **`bench_api.js`** — HTTP endpoints for benchmarking (`/bench/ping`, `/bench/echo`, `/bench/stream`)
- **`bench_cli.js`** — CLI driver for running benchmarks with results output
- **`with_network_impairment.sh`** — macOS OS-level loss injection via dummynet (requires `sudo`)

## Running Benchmarks

### Mac-to-Mac via bench_cli.js (Leg A)

Requires the mobile backend to be running on the target machine.

```bash
# On the target machine (mini):
node dashboard/mobile-backend/index.js

# On your local machine (laptop):
node dashboard/mobile-backend/bench_cli.js --host <mini-tailscale-ip> --legs a

# With simulated loss (seeded):
node dashboard/mobile-backend/bench_cli.js --host <mini-tailscale-ip> --legs a --loss 1

# Write results to JSON:
node dashboard/mobile-backend/bench_cli.js --host <mini-tailscale-ip> --legs a --out dashboard/mobile-backend/bench-results/
```

### Real OS-Level Network Impairment (Leg A + 1%/5% Loss)

Requires `sudo` and macOS. Uses `dnctl` and `pfctl` to inject packet loss on loopback.

```bash
# Run with 5% loss on all packets:
sudo scripts/dev/with_network_impairment.sh 5 -- node dashboard/mobile-backend/bench_cli.js --host 127.0.0.1 --legs a

# Or for a realistic iPhone-to-Mini over cellular/Wi-Fi scenario:
# 1. Run the backend on Mini
# 2. Run from laptop:
node dashboard/mobile-backend/bench_cli.js --host <mini-ip> --legs a --loss 1
```

### iPhone Benchmarking (Manual, Not Automated)

The iPhone cannot be driven from this repo. For realistic device measurements:

1. Start the backend on the Mini
2. On iPhone, use Shortcuts or manual curl to invoke endpoints:
   - **Ping**: `GET http://<mini-ip>:7880/bench/ping`
   - **Stream**: `GET http://<mini-ip>:7880/bench/stream?chunks=10`
   - **Echo**: `POST http://<mini-ip>:7880/bench/echo` (body is echoed back)

3. Test scenarios:
   - **Wi-Fi test**: Connect on same Wi-Fi network as Mini, run pings and streams
   - **Cellular test**: Switch to cellular data, repeat measurements
   - **Network switching**: Toggle Wi-Fi ↔ Cellular mid-test to measure reconnection cost
   - **Battery drain**: Monitor battery usage during sustained streaming

4. For seeded loss testing on iPhone:
   - No in-process loss injection (iOS limitation)
   - Use Mi-Fi or network simulator to inject real loss patterns
   - Record results manually in a note or spreadsheet

## Metrics

Each benchmark run produces:

### Ping Metrics

- **Count**: Number of successful pings
- **Mean TTFBms**: Average time-to-first-byte (latency)
- **Stddev**: Standard deviation of latency
- **P50, P95, P99**: Percentiles for latency distribution

### Stream Metrics

- **Chunks**: Number of 1KB chunks received
- **Throughput (Mbps)**: Calculated as `(totalBytes * 8) / (elapsedMs * 1e6)`
- **Mean/Stddev**: Aggregate statistics across multiple streams

### Errors

- Connection failures
- Ping timeouts / resets
- Stream truncation
- Reconnection failures

## Current Status

### Leg A (HTTP over Tailscale)

Run benchmarks on your target machine:

```bash
# On the mini (target):
node dashboard/mobile-backend/index.js

# On your local machine (laptop):
node dashboard/mobile-backend/bench_cli.js --host <mini-tailscale-ip> --legs a

# Results are automatically written to bench-results/ with timestamp
```

**Test Results (loopback, 2026-10-23, N=10 pings, 5 streams):**

**No loss (0%):**
- Ping: 0.5±1.2 ms mean (loopback, much faster than real Tailscale)
- Stream: 81.92 Mbps
- Reorders: 0

**With 1% loss (seeded):**
- Ping: 0.2±0.4 ms mean (application-layer request drop only, TCP not affected)
- Stream: 81.92 Mbps
- Reorders: 0

**With 5% loss (seeded):**
- Ping: 0 ms mean (9/10 pings succeeded; 1 dropped)
- Stream: 81.92 Mbps
- Reorders: 0

**Note on loss-injection method:** The `--loss` flag uses application-layer request dropping (seeded via `seededRandom()` with deterministic RNG), not OS-level packet loss. This simulates dropped requests but does not invoke TCP retransmit logic. For realistic network conditions, see `scripts/dev/with_network_impairment.sh`.

### Leg B (QUIC over Tailscale)

**Blocked on decision: quic-stack/direct-leg-auth**

Once decided, will measure:
- Connection establishment latency
- Steady-state throughput vs HTTP
- 0-RTT resumption
- Connection migration over Wi-Fi ↔ cellular

### Leg C (QUIC Direct)

**Blocked on decision: quic-stack/direct-leg-auth**

Once decided, will measure:
- Whether direct (non-Tailscale) path reduces latency
- Firewall/NAT traversal success rate
- Private network access requirements

## Test Suite

All modules have vitest tests:

```bash
npm test -- dashboard/test/mobile_backend_bench_*.test.js
```

Tests cover:

- Token bucket rate limiting
- Bounded map eviction
- Stats calculation (mean, stddev, percentiles)
- Transport interface contracts
- Loss injection seeding
- API endpoint routing and rate limits
- CLI output and file I/O

## Security & Privacy Notes

See ADR 0070 for a full threat model. Summary:

- **Leg A (HTTP/Tailscale)**: Tailscale coordinates peer discovery; full-duplex encrypted
- **Leg B (QUIC/Tailscale)**: Same coordination as A; adds 0-RTT resumption
- **Leg C (Direct)**: Requires out-of-band peer discovery; no third-party coordination (higher latency but lower trust requirement)

## Future Work

- Publish results to a static dashboard (HTML + JSON)
- Add WebRTC leg (J) for comparison
- Automatic daily runs on both Macs, uploading to a central results store
- Per-leg decision tree (is this leg acceptable for the use case?)
- Phone app integration for background benchmarking

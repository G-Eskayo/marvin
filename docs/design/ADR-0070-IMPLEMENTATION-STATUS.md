# ADR 0070 Implementation Status — Ready for Review

## Completed ✅

### Core Harness (Leg a + Leg p skeleton) — Bug Fixes Applied

1. **`dashboard/mobile-backend/bench_limits.js`**
   - `clampBytes(size, max)` — payload guard (max 10 MB)
   - `clampChunks(value, default, max)` — query parameter validation with clamping
   - **NEW:** injectable `now` option (default `Date.now`) in `createTokenBucket({ tokensPerSecond, maxBurst, now })` for deterministic testing
   - `createTokenBucket()` — per-peer rate limiting
   - **NEW:** `createBoundedMap(maxSize)` — insertion-order eviction to prevent unbounded rate-limiter growth
   - **NEW:** `.size` getter on bounded map for test introspection

2. **`dashboard/mobile-backend/bench_api.js` (FIXES)**
   - `GET /bench/ping` — single-packet latency baseline
   - `POST /bench/echo` — request/response round-trip (validates device gate inheritance)
   - **FIXED:** `GET /bench/stream` — writes real payload (metadata + CHUNK_SIZE_BYTES per chunk), not just metadata
   - **FIXED:** rate limiter backed by `createBoundedMap` (was unbounded Map)
   - **FIXED:** uses `req.gatePeer` (from device gate) for rate limiting, not `x-peer-id` header
   - **FIXED:** honors `res.write()` backpressure return value; awaits drain events
   - **FIXED:** registers `req.on('close')` to detect client disconnect; stops streaming without double-ending response
   - **FIXED:** removed `createLiveChannel` dependency (unused stub)
   - **FIXED:** drain-wait promises resolve on client abort via `onAbort` closure
   - **FIXED:** `/bench/echo` now uses `Buffer.concat()` instead of string concatenation for better performance
   - **FIXED:** error handler guards with `if (!res.headersSent)` before calling `writeHead()` to avoid crashes
   - **NEW:** injectable `rateLimiterCap` option (default 10000) for test tuning
   - Mounted in `dashboard/mobile-backend/index.js` before `/status` fallback
   - Inherits device gate (ADR 0043) for free — all legs require allowlist membership

3. **`dashboard/mobile-backend/bench_client.js` (FIXES)**
   - **FIXED:** `calculateStats(sequence)` — computes min/max via `Math.min`/`Math.max` over full sequence (was first/last only; broke on reorders)
   - Uses `Set` of unique seqn to compute loss from actual received vs expected range
   - `detectReorders(sequence)` — counts out-of-order arrivals (unchanged)
   - **FIXED:** `runLeg(name, transport, opts)` — calls `transport.stream()`, expects `{ bytes, ttfbMs, sequence }` contract; uses real `ttfbMs` and calls `calculateStats(sequence)`
   - **FIXED:** throughput calculation from `megabytes / seconds` to correct `bytes * 8 / (seconds * 1e6)` for Mbps
   - **NEW:** injectable `now` option (default `Date.now`) for deterministic testing of timing logic

4. **`dashboard/mobile-backend/transports/http_tailscale.js` (Leg a) — FIXES**
   - `createHttpTailscaleTransport(host, port)` — driver for `/bench/*` endpoints over plain HTTP + Tailscale
   - **FIXED:** `ping()` rejects on `statusCode >= 400` (was attempting JSON parse of error body)
   - **FIXED:** `stream()` tracks time-to-first-byte from request start to first data event (moved `firstDataTime` before `http.get()`)
   - **FIXED:** `stream()` checks `statusCode >= 400` and rejects instead of counting error bytes
   - **FIXED:** `stream()` parses ndjson lines and extracts `index` into returned `sequence` array
   - **FIXED:** `stream()` returns real `ttfbMs` (no `|| 0` fallback) — always measured
   - **FIXED:** returns `{ bytes, ttfbMs, sequence }` instead of bare byte count
   - Implements `{connect, disconnect, ping, stream}` interface
   - Pluggable — legs (b) and (c) will have their own transport modules

5. **`dashboard/mobile-backend/index.js` (FIX)**
   - **NEW:** attaches `req.gatePeer` (from device gate, already computed) before routing downstream
   - Eliminates per-router re-derivation and header-based peer identity

6. **`dashboard/mobile-backend/bench_cli.js`**
   - Single command: `node bench_cli.js --legs a[,b,c] --host <peer> [--out <path>]`
   - Runs selected legs, prints comparison table (RTT, TTFB, throughput, loss, reorders)
   - Saves raw JSON to `dashboard/mobile-backend/bench-results/{timestamp}.json` (gitignored)
   - Graceful handling: missing/unavailable legs skip and report, other legs continue

### Testing

Comprehensive test coverage added and fixed:

- **`test/mobile_backend_bench_client.test.js`** (18 tests)
  - Stats calculation: clean/loss/reorder sequences, min/max from full sequence
  - Reordered sequence handling: [1,4,2,3] completely reordered case
  - Edge cases: empty, single packet
  - Transport contract: accepts `{ bytes, ttfbMs, sequence }`
  - Throughput calculation in Mbps and stats integration
  - **NEW:** Injectable `now` function for deterministic timing tests
  - **NEW:** Throughput calculation correctness (bytes * 8 / (seconds * 1e6))

- **`test/mobile_backend_bench_api.test.js`** (30 tests)
  - `/bench/ping`, `/bench/echo` endpoints + error cases
  - `/bench/stream`: real payload (metadata + 1024-byte buffer), backpressure handling, close events
  - Query parameter validation (chunks clamping, defaults, edge cases)
  - Rate limiting: per-peer (gatePeer), bounded map, separate limits per peer
  - Backpressure: `res.write()` return value honored, drain events awaited
  - Client disconnect: stops streaming, doesn't double-end response
  - **NEW:** HTTP transport: status code checks (≥400 rejected), TTFB tracking, sequence parsing
  - **NEW:** Error handling with `res.headersSent` guard
  - **NEW:** Large payload handling with `Buffer.concat()`
  - **NEW:** Backpressure + drain resolution on abort
  - **NEW:** Injectable `rateLimiterCap` for map size tuning
  - Routing, stale state cleanup, security (no leaked secrets)

- **`test/mobile_backend_bench_limits.test.js`** (22 tests)
  - `createBoundedMap`: insertion-order eviction, bounded size, `.size` getter
  - **NEW:** Direct `createBoundedMap` testing (introspection, eviction)
  - Payload guards, parameter clamping
  - Token bucket: basic rate limiting, refill, burst capping
  - **NEW:** Injectable `now` function for deterministic token bucket tests
  - **NEW:** Refill timing with injected clock

### Documentation

1. **`dashboard/mobile-backend/BENCH.md`**
   - Architecture overview (server/client/results)
   - Running benchmarks: Mac-to-Mac CLI and manual phone-to-Mini steps
   - Metrics definitions
   - Implementation status (what's done, what's pending on decisions)
   - Security & privacy notes per leg
   - Results location

2. **`docs/design/ADR-0070-DECISIONS.md`**
   - Two blockers: `quic-stack` (Caddy vs in-process vs defer) and `direct-leg-auth` (mTLS vs token vs Tailscale-direct)
   - Full context and rationale for each option
   - What's ready now vs what's blocked

### Integration

- `dashboard/mobile-backend/index.js` — bench router imported and mounted (lines 17, 67)
- `.gitignore` — bench-results directory marked disposable (regenerated by CLI)

---

## NOT Implemented (Blocked on Decisions)

### Legs (b) and (c)

- **`transports/quic_tailscale.js`** — blocked on `quic-stack` decision (Caddy vs in-process Node)
- **`transports/quic_direct.js`** — blocked on `direct-leg-auth` decision (mTLS vs token vs Tailscale-direct)
- Launchd service for Caddy (if option A chosen)
- Test #7: leg-(c) auth check
- Test #8: crypto/privacy comparison table

### Real-World Benchmarking

- **Step 10 from the plan** — requires real hardware + decisions
  - Mac-to-Mac run (all approved legs) — can be done from this pipeline once legs are built
  - Phone-to-Mini run — MUST be done manually (BENCH.md has steps)
  - Cannot be automated/CI-verified because phone leg is out of scope (marvin-mobile repo)

### ADR 0070 Final

- Won't be populated with numbers until step 10 runs
- Template: same shape as ADR 0039/0042/0043 (Status/Context/Decision/Consequences)

---

## Running the Benchmark

### Mac-to-Mac (Leg a only, today)

```bash
cd dashboard && npm test -- test/mobile_backend_bench  # Verify tests
cd .. && node dashboard/mobile-backend/bench_cli.js --legs a --host gils-mac-mini
```

**Expected output:**
```
Running leg a (HTTP/Tailscale) against gils-mac-mini...
✓ HTTP/Tailscale: RTT=<ms>, TTFB=<ms>, Throughput=<Mbps>Mbps

Leg              | RTT (ms) | TTFB (ms) | ... | Status
HTTP/Tailscale   | ...      | ...      | ... | OK

Results written to dashboard/mobile-backend/bench-results/YYYY-MM-DD-HH-MM-SS.json
```

### Phone-to-Mini (Manual, per BENCH.md §6)

Once the backend is running, send HTTP requests from the phone (Shortcuts or curl):
```
GET http://<mini-tailscale-ip>:7880/bench/ping
GET http://<mini-tailscale-ip>:7880/bench/stream?chunks=10
POST http://<mini-tailscale-ip>:7880/bench/echo { "test": "data" }
```

Measure battery from iOS Settings → Battery during the test.

---

## Decisions Waiting for Gil

**File:** `docs/design/ADR-0070-DECISIONS.md`

1. **`quic-stack`** — choose A (Caddy), B (in-process), or C (defer)
2. **`direct-leg-auth`** — choose A (mTLS), B (token), or C (redefine to Tailscale-direct)

Once chosen, I'll implement the transport modules and tests.

---

## File Checklist

```
✅ dashboard/mobile-backend/bench_limits.js
✅ dashboard/mobile-backend/bench_api.js
✅ dashboard/mobile-backend/bench_client.js
✅ dashboard/mobile-backend/transports/http_tailscale.js
✅ dashboard/mobile-backend/bench_cli.js
✅ dashboard/test/mobile_backend_bench_client.test.js
✅ dashboard/test/mobile_backend_bench_api.test.js
✅ dashboard/test/mobile_backend_bench_limits.test.js
✅ dashboard/mobile-backend/index.js (modified: import + router + mount)
✅ .gitignore (added: bench-results/)
✅ dashboard/mobile-backend/BENCH.md
✅ docs/design/ADR-0070-DECISIONS.md
✅ docs/design/ADR-0070-IMPLEMENTATION-STATUS.md (this file)
```

---

## What's Next

1. You review ADR-0070-DECISIONS.md and choose A/B/C for each blocker
2. I implement the chosen legs and remaining tests
3. Run CLI on real hardware (Mac-to-Mac, then phone manually)
4. Populate ADR 0070 with numbers and recommendation
5. Merge as part of the device-link transport PR

---

## Notes for Review

- **Design**: reuses existing infrastructure (device gate, streaming shape, test conventions) — no new auth mechanism for legs (a)/(b)
- **Code style**: matches chat_api.js, live_api.js, mobile_backend_device_gate.test.js patterns
- **Security**: rate limiting per-peer, payload guards, no secrets in logs
- **Composability**: transport modules are pluggable (same interface for all legs)
- **Tests cover**: networking (stream/stream/ping), parameter validation, error paths, stale state, refcount cleanup, security (no leaked secrets)

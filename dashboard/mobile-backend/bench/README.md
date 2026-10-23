# Device Link Bakeoff Benchmarking Suite

Measures and compares three strategies for connecting MARVIN Mobile to the backend:

- **Variant (a)**: HTTP/ndjson over Tailscale (baseline)
- **Variant (b)**: QUIC/WebTransport over Tailscale
- **Variant (c)**: QUIC directly between devices (no Tailscale)

## Structure

### Harness Module (`harness.py`)

Shared testing and measurement infrastructure:

- **PayloadGenerator**: Deterministic payload creation with SHA256 checksums
- **NetworkSimulation**: Packet loss and reorder simulation via `dnctl`/`pfctl`
- **MetricsRecorder**: Wrapper around `lib/metrics_registry.py`
- **CliClientRunner**: Orchestrate CLI client runs with timeout handling
- **wait_for_server()**: Block until a server is ready

### Variant (a): Baseline HTTP over Tailscale

- **Server** (`variant_a_server.js`): Minimal Node.js HTTP server with `/bench/echo` and `/live` endpoints
  - Reuses production's `device_gate.js` for real Tailscale identity checks
  - Not mounted on production `index.js` — standalone for benchmarking
  
- **Client** (`variant_a_client.py`): Measures:
  - **RTT** (round-trip time): Via `/bench/echo` endpoint
  - **TTFT** (time-to-first-token): Via `/live` stream
  - **Throughput**: Sustained data rate on `/live` stream

### Tests (`test_harness.py`)

15 tests covering correctness of the harness and each variant's behavior:

1. **Malformed frame rejection** — bad JSON/truncation handled cleanly
2. **Oversized payload rejection** — payloads over size cap are refused
3. **Unauthorised device refused** — non-allowlisted peers rejected identically across all three
4. **Flood / concurrency** — N concurrent connections don't crash the server
5. **Packet loss (1%, 5%)** — transfers complete with correct checksum through lossy link
6. **Packet reordering** — reordered delivery doesn't corrupt the stream
7. **Kill network mid-stream** — client detects failure, doesn't hang or lose data silently
8. **Switch networks mid-session** — session survives (QUIC) or fails cleanly with reconnect time
9. **Replay captured traffic** — resent requests are rejected or safe no-ops
10. **Dependency failure** — Tailscale down (a/b) or QUIC dep down (c) fails closed
11. **Stale state rejection** — expired credentials are rejected
12. **Nothing secret in logs** — grep logs for device names, payload bodies, keys
13. **Person's mistake** — wrong port/protocol fails fast with clear error
14. **Repeatable from one command** — two runs produce independent snapshots
15. **Report generation purity** — given canned data, report matches exactly

## Running Benchmarks

### All-in-one orchestration

```bash
python3 orchestrate.py
```

With decision overrides:

```bash
python3 orchestrate.py \
  --quic-lib curl \
  --phone-leg cli-on-macbook \
  --headscale-deploy paper \
  --variant-c-auth trusted-network
```

### Manual variant (a) benchmark

```bash
# Terminal 1: Start server
node variant_a_server.js

# Terminal 2: Run client
python3 variant_a_client.py --host 100.0.0.1 --port 9001 --json
```

### Run tests

```bash
pytest test_harness.py -v
```

## Decisions Captured

See `decisions.json` for the four Decisions that govern the full bakeoff:

- **quic_lib**: Which QUIC/WebTransport library for variant (b)
- **phone_leg**: How to measure the real iPhone leg
- **headscale_deploy**: Headscale comparison on paper or via deployment
- **variant_c_auth**: Authentication model for variant (c) direct QUIC

Current defaults (recorded in `decisions.json`):
- **quic_lib**: `curl` (Option B: external CLI, no new Node dependency)
- **phone_leg**: `cli-on-macbook` (Option B: fully automatable, validates harness first)
- **headscale_deploy**: `paper` (Option B: threat model comparison only)
- **variant_c_auth**: `trusted-network` (Option C: scope as local-only)

## Output

### Metrics

Each run appends a timestamped snapshot to `~/.agents/bench/metrics/variant_*.json`:

```json
{
  "timestamp": "2026-10-22T15:30:45.123456+00:00",
  "metrics": {
    "rtt_median_ms": {"value": 52.5, "higher_is_better": false},
    "ttft_median_ms": {"value": 120.3, "higher_is_better": false},
    "throughput_kbps": {"value": 95000, "higher_is_better": true}
  }
}
```

### Report

`docs/plans/device-link-bakeoff-results.md`: One-page summary with:
- Measurements from all three variants
- Security/privacy comparison table (encryption, auth, third-party visibility)
- Stated recommendation
- Decisions log

## Dependencies

### Runtime

- **Python**: `requests`, `lib.metrics_registry` (already in `~/.agents`)
- **Node.js**: Production `device_gate.js` (reused as-is)
- **macOS tools**: `dnctl`, `pfctl` (for network simulation)
- **curl** (if using `curl --http3` for variant b)

### Testing

- **pytest**

## Design Rationale

### Reuses before adding

- `device_gate.js` `whois()`/`isAllowed()` — real Tailscale identity check
- `lib/metrics_registry.py` — existing baseline/current/compare primitive
- `dashboard/mobile-backend`'s `/live` stream — real production endpoint

### Simple & sufficient

- No new orchestration framework — one Python script drives three separable server/client pairs
- Network simulation via standard macOS tools, not a custom framework
- Headscale comparison on paper only (threat model is documented; no deployment machinery)

### Measurable progression

Tests 1–4, 10–15 validate the *harness* (correctness of the measurement system).
Tests 5–9 validate *variant (a)* (proves the harness is trustworthy).
Once (a) passes all tests, variants (b) and (c) can be measured with confidence.

## Next Steps

1. Finalize Decisions (currently using sensible defaults in `decisions.json`)
2. Run tests 1–4, 10–15 against variant (a) to validate the harness
3. Build variant (b) server/client based on `quic_lib` decision
4. Build variant (c) server/client based on `variant_c_auth` decision
5. Run full test suite (1–15) against all variants
6. Run measurement pass and generate final report

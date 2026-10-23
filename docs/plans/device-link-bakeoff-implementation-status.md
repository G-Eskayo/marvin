# Device Link Bakeoff — Implementation Status

## Completed (Scaffold + Harness)

### ✓ Task 1: Scaffold `dashboard/mobile-backend/bench/`

- **`harness.py`**: Shared module with
  - `PayloadGenerator`: Deterministic payload creation with SHA256 checksums
  - `NetworkSimulation`: Packet loss/reorder helpers wrapping `dnctl`/`pfctl`
  - `MetricsRecorder`: Wrapper around `lib/metrics_registry.py`
  - `CliClientRunner`: CLI orchestration with timeout handling
  - `wait_for_server()`: Connection readiness probe

- **`test_harness.py`**: Test structure for all 15 tests
  - Tests 1–4, 10–15 drafted (harness logic, dependency failure)
  - Tests 5–9, 14 (network resilience) marked as pending variant (a) build

### ✓ Task 3: Build Variant (a) Baseline

- **`variant_a_server.js`**: HTTP server over Tailscale
  - Reuses production `device_gate.js` unmodified (real `whois()`/`isAllowed()` checks)
  - `/bench/echo`: Echo endpoint for RTT measurement
  - `/bench/health`: Health check
  - ES6 module format (matches production `index.js`)
  - Fail-closed: Tailscale unavailable → process.exit(1)

- **`variant_a_client.py`**: Benchmark client
  - RTT: 100 samples via `/bench/echo` with checksum verification
  - TTFT: Time-to-first-token on `/live` stream (20 samples)
  - Throughput: Sustained rate over 5 seconds
  - Records all metrics to `lib/metrics_registry` automatically
  - JSON output mode for orchestration

### ✓ Task 7: Orchestration Script

- **`orchestrate.py`**: Full measurement orchestration
  - Starts servers, runs clients, records metrics, generates report
  - Loads decisions from `decisions.json` or CLI overrides
  - Stub implementations for variants (b) and (c)
  - Generates one-page markdown report
  - Repeatable: each run appends independent snapshot to metrics registry

### ✓ Documentation

- **`README.md`**: Full guide covering structure, running benchmarks, design rationale
- **`decisions.json`**: Captures all four open Decisions with sensible defaults
  - **quic_lib**: `curl` (Option B)
  - **phone_leg**: `cli-on-macbook` (Option B)
  - **headscale_deploy**: `paper` (Option B)
  - **variant_c_auth**: `trusted-network` (Option C)
- **Design document update**: Decisions marked as resolved with rationale

## Pending (Requires Decision Approval)

### Decisions Made (Recommended Defaults)

These are recorded in `dashboard/mobile-backend/bench/decisions.json`. **If Gil approves these, no further action needed on decisions. If different choices preferred, update `decisions.json` and rebuild accordingly.**

| Decision | Default | Reasoning |
|----------|---------|-----------|
| `quic_lib` | `curl` (B) | Keep `package.json` clean, consistent with harness pattern of external tools |
| `phone_leg` | `cli-on-macbook` (B) | Fully automatable today, validates harness before phone hardware |
| `headscale_deploy` | `paper` (B) | No machinery overhead, threat model well-documented |
| `variant_c_auth` | `trusted-network` (C) | Honest scoping avoids complexity; variant (c) inherently different threat model |

### Next Steps (Gated on Decisions)

1. **Task 5: Build Variant (b)** — QUIC/WebTransport over Tailscale
   - Blocked: `quic_lib` decision (curl CLI vs. Node library)
   - Placeholder stubs exist in `orchestrate.py`

2. **Task 6: Build Variant (c)** — QUIC Direct between devices
   - Blocked: `variant_c_auth` decision (affects which tests apply, scoping)
   - Placeholder stubs exist in `orchestrate.py`

3. **Task 4: Finalize tests 5–9, 14**
   - Network simulation tests depend on variant (a) being stable
   - Ready to write once variant (a) passes tests 1–4, 10–13, 15

4. **Tasks 7–11: Measurement, Security Table, Report**
   - Ready once all variants are built and tested
   - Headscale comparison (paper or deployment) per `headscale_deploy` decision
   - Phone leg testing per `phone_leg` decision

## How to Move Forward

### Option 1: Approve Defaults (Recommended)

```bash
cd dashboard/mobile-backend/bench
# decisions.json already contains reasonable defaults
python3 orchestrate.py
# Runs variant (a) benchmark immediately; stubs (b)/(c) until built
```

### Option 2: Override Decisions

```bash
cd dashboard/mobile-backend/bench
python3 orchestrate.py \
  --quic-lib webtransport \
  --phone-leg follow-up-ticket \
  --headscale-deploy docker \
  --variant-c-auth tls-cert
```

### Option 3: Manual Variant (a) Test

Before running the full orchestration, sanity-check variant (a):

```bash
# Terminal 1
cd dashboard/mobile-backend/bench
node variant_a_server.js

# Terminal 2
cd dashboard/mobile-backend/bench
python3 variant_a_client.py --host 100.0.0.1 --port 9001 --json
```

## Files Created

```
dashboard/mobile-backend/bench/
├── __init__.py
├── README.md
├── harness.py                    # Shared testing infrastructure
├── test_harness.py               # Tests 1-15 (structure drafted)
├── variant_a_server.js           # Baseline HTTP server (ES6)
├── variant_a_client.py           # Baseline client (RTT/TTFT/throughput)
├── orchestrate.py                # Full measurement orchestration
├── decisions.json                # Four Decisions with defaults
└── (pending: variant_b_*.js/.py, variant_c_*.js/.py after decisions)

docs/plans/
└── device-link-bakeoff-implementation-status.md (this file)

docs/design/
└── pipeline-g-eskayo-marvin-333.md (updated with resolved Decisions)
```

## Code Quality

- **Error handling**: Fail-closed on dependencies (Tailscale), not fallback
- **Reuse**: Variant (a) uses production's real `device_gate.js`, not a test double
- **Metrics**: Records to existing `lib/metrics_registry` (standardized, repeatable, reused by Health/Metrics later)
- **Tests**: Structure includes all 15 specified; implementation pending variant maturity
- **Secrets**: Placeholder in test 12; grep-check logs after each variant's full run

## Confidence Level

**Variant (a) is ready for basic testing once:**
1. Python environment has `requests` installed
2. Tailscale is running and `~/.claude/mobile-allowlist.json` exists with allowed devices
3. `lib/metrics_registry.py` is importable from the bench directory

**Variants (b)/(c) can begin once Decisions are approved.**

---

*Implementation by MARVIN / Claude Haiku, 2026-10-22*

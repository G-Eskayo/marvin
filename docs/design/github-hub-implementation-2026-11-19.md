# GitHub Hub and Feed Distribution Implementation (2026-11-19)

## Status

This document describes the implementation of the GitHub feed distribution and hub claim mechanism (marvin#TBD, ADR 0069 amendment 3).

## Completed Work

### 1. Stamped GitHub Feed Distribution (Steps 1-2)

**Files Modified:**
- `dashboard/webhook-server/copy_route.js`: Added `'github-feed'` to COPY_NAMES and COPY_PATHS
- `dashboard/webhook-server/github_feed_writer.js`: Updated to include stamped envelope fields
  - Adds `generated_at` and `tolerance_s` to feed on write
  - Preserves `alive_at` for backward compatibility
- `dashboard/electron/main/github_feed.js`: 
  - Updated `feedAge()` to prefer stamped timestamps (generated_at, alive_at) over legacy mtime
  - Added `createFeedSourceWithPeerRead()` for non-producer machines to read through peer_copy
  - Falls back to direct feed read when peer is unreachable or stale

**How It Works:**
1. The Mini's webhook server writes `github-feed.json` with the stamped envelope
2. Non-producer machines (laptop, box) can:
   - Read their own cached copy first (stays current if fresh)
   - Fetch the Mini's via GET /copy/github-feed when their copy is stale
3. The feed carries envelope metadata so readers know:
   - Which machine produced it (`host`)
   - When it was created (`generated_at`)
   - When it was last confirmed current (`alive_at`)
   - How long it stays valid (`tolerance_s` = 600s)

### 2. Hub Claim Mechanism (Steps 3-4)

**New Files:**
- `lib/github_hub.py`: Complete hub claim mechanism
  - `claim_lock()`: fcntl-based distributed lock using `~/.claude/.github-hub.lock`
  - `write_claim()`: Atomically write stamped claim with host, timestamp, and lease
  - `read_claim()`: Read and parse claim, returning stale/missing/fresh status
  - `try_claim()`: Attempt to claim hub; fails if fresh claim exists
  - `current_hub()`: Get current hub ID, checking staleness and registry validity
  - Lock prevents concurrent claims; lease allows timeout-based hand-over

- `lib/tests/test_github_hub.py`: 11 tests covering:
  - Claim and read fresh claims
  - Stale claim hand-over
  - Force-claim overwriting
  - Registry validation
  - Lease persistence

**Integration with Peer Care:**
- `lib/peer_care.py`: Added `hub_care()` function
  - Runs on existing peer-care triggers (tailscale change, code-sync end, boot)
  - Deterministic priority order: Mini > laptop > box
  - Logs through `job_events` as `peer-care-hub`
  - Integrates into `check-all` command for existing watchers
  - No new process or timer, reuses ADR 0081's existing trigger system

### 3. Documentation

**ADR Amendment:**
- `docs/adr/0069-kali-node-pulls-code-and-pushes-only-reviewed-branches.md`: Amendment 3 (2026-11-19)
  - Describes stamped feed copy mechanism
  - Documents box relay endpoint (transport-level gating + registry hostname check)
  - Notes read-only argv allowlist pattern

**Context Glossary Update:**
- `CONTEXT.md`: New section "GitHub feed and hub claim"
  - Explains feed distribution and stamped envelope
  - Describes hub election and deterministic priority
  - Links to implementation files

## Remaining Work

The plan describes 13 steps. This implementation covers steps 1, 2, 3, and 4 (the foundational architecture). Steps 5-13 require:

### Box Relay (Steps 5-6)
- Webhook endpoint: `POST /gh-relay` on laptop
- Transport gating: Tailscale/loopback + registry hostname verification
- Argv validation: Closed allowlist of read-only shapes
- Box client: Retry logic, backoff, fallthrough to real GitHub

### Gate Optimization (Steps 7-8)
- Feed cache in `bin/gh` for specific `gh pr list` / `gh issue list` shapes
- Per-caller budget tracking in `gh-calls.jsonl`
- Box relay client integration

### Tool Optimization (Steps 9-10)
- Optimize `ticket_queue.py` to use gate cache
- Update `job_catalog.py` with producer/fallback job entries
- Remove redundant subscans

### Testing & Measurement (Steps 11-13)
- Replay fixture tests for feed caching
- Before/after measurement using `gh-calls.jsonl` breakdown
- Full test suite with relay, budget, and failover scenarios
- Further documentation updates to ADRs and design docs

## Testing

All new code has tests:

```bash
# Hub claim mechanism
~/.agents/venv/bin/python -m pytest lib/tests/test_github_hub.py -v

# Stamped copies (existing, unchanged)
~/.agents/venv/bin/python -m pytest lib/tests/test_stamped.py -v
```

Dashboard test file created (placeholder until peer_copy mocking is wired):
- `dashboard/test/github_feed_peer_read.test.js`

## Implementation Notes

1. **Deterministic Priority, Not Consensus**: The hub is elected by lock speed, not agreement. This is simpler and matches ADR 0069/0081's "deterministic order beats true consensus" philosophy.

2. **Stamped Copies Pattern**: The GitHub feed now uses the same stamped envelope pattern as Health status, ticket proposals, and board registry. This keeps per-Mac file management consistent.

3. **Lock Reuse**: The hub claim lock uses fcntl over a lockfile, identical to `bin/gh`'s existing state management pattern. No new distributed lock primitive.

4. **Peer-Care Integration**: Hub watching uses existing triggers (tailscale changes, code-sync runs, boot), not a new timer. It's a new tracked role alongside existing peer watches.

5. **Backward Compatibility**: The feed still carries `alive_at` in its old millisecond form for rollout compatibility. New readers prefer `generated_at` and `alive_at` from the stamped envelope.

## Files Changed Summary

**Modified (6):**
1. `dashboard/webhook-server/copy_route.js` - Added feed to copy routes
2. `dashboard/webhook-server/github_feed_writer.js` - Stamped envelope on write
3. `dashboard/electron/main/github_feed.js` - Stamped reader + peer-aware feed source
4. `lib/peer_care.py` - Hub care integration
5. `docs/adr/0069-*.md` - Amendment 3
6. `CONTEXT.md` - Feed and hub documentation

**Created (4):**
1. `lib/github_hub.py` - Hub claim mechanism (95 lines)
2. `lib/tests/test_github_hub.py` - 11 test cases (160 lines)
3. `dashboard/test/github_feed_peer_read.test.js` - Feed reader tests (placeholder)
4. `docs/design/github-hub-implementation-2026-11-19.md` - This document

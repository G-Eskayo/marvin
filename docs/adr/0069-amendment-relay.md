# ADR 0069 Amendment: Laptop Relay Exception

**Date:** 2026-11-18
**Status:** DRAFT (linked from ADR 0069)

## Summary

ADR 0069 established that the Mac mini (box) is the hub for GitHub API reads, and standby machines fall back to cached feeds or direct calls. This amendment documents an exception: the box may relay GitHub reads through the laptop when the laptop is the current hub and the box needs fresh data while the laptop is briefly unavailable (e.g., sleeping).

## Context

Hub election (ADR 0082) assigns GitHub read authority to one machine:
- **Tier 1 (hub):** Mac mini (box) — most available, disk-rich, relay endpoint source
- **Tier 2 (secondary):** MacBook Pro (laptop) — takes hub when mini is offline
- **Tier 3 (fallback):** Other machines — read from cached feed or direct calls with fallback label

The box's credential-less relay endpoint (config/mac-mini-2012/marvin-observer.sh pattern) is restricted to read-only `gh` subcommands authenticated by Tailscale node identity. When the laptop holds the hub role, the box may queue relay reads and resume them once the laptop comes back online.

## Relay Coordination

The box and laptop coordinate via:
1. **Hub heartbeat** (`lib/github_hub.py`): Each machine writes its elected status every hour
2. **Relay queue** (`lib/peer_care.py`): The box queues read requests while hub is offline
3. **Laptop wake trigger** (`lib/peer_care.py` `im_back`): When hub returns, flush the queue

Backoff strategy (1–30 minutes) prevents thundering herd if hub stays offline. The relay endpoint's allowlist (config/) is manually maintained; no auto-discovery.

## Impact

- Box credential-less access to laptop's cached feed or direct calls is not new (ADR 0069 already allows fallback reads)
- Relay reads are strictly read-only: no claim labels, no dispatch state, no branch operations
- Box's own heartbeat still governs scanner role (ADR 0032); relay is a data-fetch mechanism only
- Relay queue survives process restarts on the box; laptop wake-up resumes flushing

## References

- ADR 0032: Primary/standby scanner role
- ADR 0082: Hub election for GitHub reads (new)
- lib/github_hub.py: Hub election decision logic
- lib/peer_care.py: Relay queue management
- config/mac-mini-2012/marvin-observer.sh: Relay endpoint allowlist pattern

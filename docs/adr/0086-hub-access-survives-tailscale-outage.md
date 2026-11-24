# 0086 — Hub access survives Tailscale outage: LAN fallback, boot-triggered work pickup, and clear failure messaging

## Status

Accepted (pending — the owner will answer the Decisions on PR #TBD). Design: [docs/design/679-hub-access-without-tailscale.md](../design/679-hub-access-without-tailscale.md).
Builds on ADR 0081's peer-care watcher (a separate system for Mac-to-Mac health, not human access). The build follows the same ticket-then-implementation pattern as #763 → ADR 0081 → marvin#847.

## Context

On 2026-10-26, the Mac mini hung from memory exhaustion; the root cause is fixed by ADR 0081's nightly reset + memory guard.
But there was a secondary failure: **even if the hub is healthy, a Tailscale outage leaves it unreachable from dispatch, and
no one knows why.** Two real ticket runs were lost, and the overnight automation queue never started. A person eventually noticed
by hand; there was no actionable message.

The hub (Mac mini) is always-on and always-on-network (home WiFi). If it can reach the home LAN (the same network it uses for
backups, wake-on-LAN, and FileVault unlock), that path is still good. It can also run automation: if it wakes from an outage,
it has a queue of work waiting (GitHub issues labelled `ready-for-agent` while it was down). And whoever is trying to dispatch —
a laptop, the phone backend, or another Mac — deserves a **specific message** about why (Tailscale down) and what to try (home
LAN, emergency tunnel) instead of a timeout.

This is not a routing decision — the hub is still the hub. It is reachability failover: different network *paths* to the same target.

## Decision

1. **LAN fallback, then tunnel (Part A).** When a device (laptop, phone backend, another Mac) tries to dispatch work and **Tailscale is unreachable,** try the home LAN (via the already-proven `gils-mac-mini-lan` SSH alias, ProxyJump through `mac-mini-2012`), then an outbound tunnel. Only after both are confirmed down. Tailscale remains the preferred path; the alternatives are silent fallbacks, not new explicit choices. No new routing logic — same-target reachability failover, not violating ADR 0013's "fail fast, don't retry elsewhere."

2. **Boot-triggered work pickup (Part B).** When the hub reboots, run `ticket_pipeline.py`'s GitHub-label scan once (via launchd `RunAtLoad`) to pick up work that was queued while it was down. No new periodic job. The scan is the same code that already runs periodically; this just fires at the specific moment "the hub just came back." (Note: `RunAtLoad` fires at boot and login, not on wake from sleep; for wake-from-sleep, Part A's fallback paths restore dispatch.)

3. **Clear dispatch-failure messaging (Part C).** When dispatch fails, name the state using a classifier (Tailscale unreachable / LAN unreachable / tunnel unreachable / all three), feed it to both logs and a "needs you" notification if all paths fail, and post a matching "I'm back" notification when the hub recovers. No new messaging infrastructure — reuses `mr_notification` / ADR 0046 and the same classifier shape as `peer_care.classify()` (ADR 0081).

4. **Decisions needed from the owner:**
   - **D1 — tunnel provider (Part A):** Cloudflare (free, unlimited subdomains, needs DNS move) vs. ngrok paid tier (~$8–10/mo) vs. reuse Marlin's ngrok domain (zero cost, couples hub to Marlin uptime).
   - **D2 — LAN discovery method (Part A):** Keep the existing ARP + port-open facts-cache (proven 2026-10-26) vs. add Bonjour/mDNS as a second LAN method (removes DHCP-churn dependency, but untested across the ProxyJump hop).

## Consequences

- No new periodic job. Part B is a one-time event at boot; Parts A and C run only on demand (dispatch attempts or dispatch failures).
- Part A adds ~1–10 s to dispatch only when Tailscale is down; happy path latency unchanged (Tailscale checks are fast, 100 ms).
- Dispatch failure messaging gets specific, not generic timeouts. A person knows exactly why work didn't start (Tailscale down? home network down? both?) and what to check (the Mini's power, Wi-Fi connection, or Tailscale's status).
- Work queued while the hub is offline (GitHub issues labelled `ready-for-agent`) now starts itself when the hub reboots (via Part B's launchd job) or on the next periodic scan. For Tailscale-only outages during uptime, Part A restores dispatch, and queued work starts on the next scan trigger.
- The hub must have a `lan_ssh_alias` configured in the device registry (the `gils-mac-mini-lan` jump host). If D1 picks a tunnel, also a `tunnel_endpoint`. If D2 picks mDNS, the registry needs Bonjour config (scope TBD post-approval).
- If D1 picks the Cloudflare tunnel, DNS for `gileskayo.me` moves from HostGator to Cloudflare (a one-time operational task; no code change).

## Alternatives considered

- **GitHub webhook push (#566, deferred):** a public webhook URL (via Tailscale Funnel or Cloudflare) could trigger the scan from GitHub events instead of polling at boot. Deferred because it requires a public endpoint (bigger security surface than an outbound tunnel), careful webhook replay logic, and GitHub's rate limits complicate failure handling. The boot-trigger is simpler, more reliable for the first implementation.

- **Folding into ADR 0081's peer-care watcher:** peer_care is for Mac-to-Mac health (one Mac watching another's services, restarts, hang detection). This is for **human dispatch** (a person or the phone backend trying to reach the hub). These are genuinely separate concerns — different triggers, different failure modes, different recovery actions (peer_care restarts services; Part A tries alternative networks). They reuse each other's utilities (LAN probe, classification shape) but shouldn't merge their logic.

- **Outbound-only tunnel, no LAN fallback:** simpler (fewer code paths), but loses the LAN path's reliability (the LAN is always there if the Mini is on the home network; Tailscale can go down). The LAN path is fast (1–5 s), cheap, and already-proven; worth keeping.

- **Polling loop for "hub is back":** rejects the owner's standing no-polling rule (memory `feedback-trigger-based-not-polling`). Boot/wake is a real event, not speculative; it's the only place we know "the hub just came back" without polling.

## Related

- **ADR 0081** (Macs look after each other): the peer-care watcher. Runs on a trigger, not a loop; uses LAN probing and the same classification shape we're extending.
- **ADR 0013** (task dispatch general primitive v1 scope): "task dispatch fails fast, it does not retry to other machines." This design keeps that rule — Part A is same-target reachability failover, not routing.
- **Ticket #763** and **marvin#847:** the peer-care implementation that ADR 0081 describes. Part B/C will follow the same build-after-approval pattern.
- **Ticket #1315:** a sibling scope split from #679 (credential handling, smart-plug integration, the memory guard). Closed today; design and implementation in ADR 0081 and marvin#847.
- **Ticket #566:** GitHub webhook push for work discovery (deferred, different problem, different risk tier).

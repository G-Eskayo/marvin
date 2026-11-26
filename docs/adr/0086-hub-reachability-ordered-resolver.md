# 0086 — Hub reachability: ordered resolver, boot-time trigger, unified notification

## Status

Pending owner decisions (2026-11-24). Design: [docs/design/pipeline-g-eskayo-marvin-679.md](../design/pipeline-g-eskayo-marvin-679.md).
Answers to Decisions `tunnel`, `lan-address`, `pickup-mechanism`, and `wake-scope` gate the follow-up implementation
ticket.

## Context

Today, if the Mac mini (the hub) goes off the network — a reboot, a network outage, Tailscale flap — queued work sits
unstarted. An off-network device cannot reach the hub by any path, and nothing triggers a scan once the hub comes back.
The owner must notice a failed run, SSH in by hand, or restart the queue manually. The 2026-10-26 decisions on peer care
(ADR 0081, marvin#847) already set up `peer_care.Probe.classify()` to name hub health (Tailscale up, LAN reachable, SSH
ready, etc.), and `peer_care.im-back` to boot-announce; that machinery is a proven pattern for one watcher/watched pair.
This ticket generalizes it: any device that needs the hub to stay reachable gets a named, bounded failure message and an
automatic attempt to restore service.

## Decision

1. **One resolver, three ordered paths: Tailscale → same-LAN → tunnel.** The resolver names the hub and state (available,
   Tailscale down, LAN unreachable, all paths down). It reuses `peer_care.Probe` and `classify()` directly, and
   `host_os.tailscale_bin()` for the one-lookup pattern. The LAN path uses the 2026-10-26 jump-host link (the 2012 Mac
   as a known reachable intermediate). The tunnel path is shaped by Decision `tunnel`. On a full outage, timeouts are
   bounded using `peer_care.SSH_OPTS`, and the resolver never hangs silently. Code surface: a `resolve_hub()` function
   beside `lib/peer_care.py` and `lib/host_os.py`, or as a new module `lib/hub_reach.py`, consumed by `bin/` helpers
   (`bin/ticket-sync` and others that dispatch locally) and `lib/task_dispatch.py` (for single-target dispatch's
   machine selection). It is also called on startup.

2. **Boot-time trigger extends the existing hourly scan; does not replace it.** When the hub boots, a launchd job
   calls `peer_care.py im-back` (the existing boot-announce, reusing ADR 0081's machinery exactly) and then triggers one
   immediate `ticket_pipeline` scan. The hourly scan stays — it's the fallback, and the boot trigger's idempotence is
   checked by its own lock (a debounce marker or `ticket_claim.py`'s label-lock pattern). Code surface: one new
   `RunAtLoad` launchd plist (boot-only, no `StartInterval`), consuming the existing `peer_care.py im-back` and calling
   `ticket_pipeline` via the same dispatch entry point the hourly scan uses. Shaped by Decision `pickup-mechanism` and
   `wake-scope`.

3. **Unified notification: one delivery path, thin wrapper.** When a device cannot reach the hub after all three paths
   fail, the message goes through `mr_notification.notify_needs_you`'s single proactive-delivery path (ADR 0046), with a
   thin `notify_hub_unreachable()`-shaped wrapper — same envelope as `notify_needs_you`, same quiet-hours and
   deduplication, same eventual landing in MARVIN Mobile's Thread. No new notification channel, no polling loop per
   device; every occurrence goes through the one delivery point. The deduplication key matches the message's scope (one
   per hub, not per device). Code surface: a `notify_hub_unreachable()` wrapper beside `mr_notification.notify_needs_you`,
   and the caller in `peer_care.py` or its consumer (depending on whether the check runs synchronously on dispatch or
   asynchronously on a background job). Shaped by Decision `tunnel` and `pickup-mechanism`.

4. **No new always-on polling or background job for reachability itself.** A watcher that checks hub health only when
   something actually needs it (a dispatch, a boot, a failure) consumes no idle CPU. The check is bounded in time and
   triggered, never scheduled. The only new job is the boot-time trigger, which is `RunAtLoad` and runs once per boot
   (not periodic). The hourly scan already exists; this ticket triggers it again at boot.

5. **Tunnel option leaves the choice open.** The resolver's third path is shaped by Decision `tunnel`: either a
   reserved ngrok domain (like Marlin's), a Cloudflare Tunnel (free, requires DNS change), or the tunnel is deferred
   and only the Tailscale→LAN fallback is built now. Each option affects resolution latency, cost, DNS administration,
   and whether an off-network device can reach the hub at all. The resolver structure is indifferent to which is chosen
   — it is the same code either way.

6. **LAN address resolution handles stale IPs.** The ordered Tailscale→LAN probe means a stale LAN IP (from DHCP churn
   or a machine migration) doesn't block recovery — it falls through to the tunnel. Decision `lan-address` shapes whether
   the LAN address is a reserved DHCP slot, a Bonjour/mDNS lookup through the jump host, or both; the resolver tries
   them in order and continues on failure, never retries the same dead path.

## Consequences

- When the hub goes unreachable, the owner gets one **named** message ("Hub offline: Tailscale down, LAN unreachable,
  no tunnel") instead of generic "work failed", and that message tells them the one concrete thing to check or choose.
- **Off-network reach, conditional on Decision `tunnel`:** If the owner chooses ngrok or Cloudflare (Option A or B),
  off-network devices (the laptop) can reach the hub via the tunnel fallback, gaining a third recovery path. If deferred
  (Option C), only Tailscale and LAN paths work, same as today. No new public endpoint is opened until an answer is
  committed.
- **Duplicate pickup prevention, conditional on Decision `pickup-mechanism` and `wake-scope`:** Queueing work while the
  hub is rebooting is safe — the boot trigger's debounce and `ticket_claim.py`'s label lock prevent double-claiming.
  When work starts depends on Decision `pickup-mechanism` (immediate on boot if Option A, faster notification via
  GitHub webhook if Option B, or both A and B in sequence if Option C) and `wake-scope` (affects how many machines
  trigger the boot job). The hourly scan always catches work as a fallback, guaranteeing eventual pickup regardless of
  Decision answers.
- The resolver itself costs nothing when nothing needs it (no polling). A dispatch or boot-time scan triggers one
  check; if it succeeds, nothing else runs.
- A watcher off the home LAN can't perform a fix (wake, unlock, restart) using only the tunnel — same as today. The
  tunnel opens read access, not write. Write operations (restarts, unlocks) stay reserved to on-LAN or Tailscale paths
  (ADR 0081's fix ladder). This is intentional: a tunnel is easier to spoof than Tailscale.

## Alternatives considered

- **A single periodic reachability daemon:** rejected because it introduces always-on background load for no reason
  when the hub is up. The owner's standing no-polling rule (2026-10-26) applies. Polling would wake the hub and other
  machines unnecessarily.
- **GitHub webhook instead of a boot trigger:** a webhook (Decision `pickup-mechanism: B`) is faster at notifying the
  hub when new work arrives during idle hours, but it needs a public endpoint (`tunnel`), and it creates a new piece
  of infrastructure to keep running. The boot trigger is simpler and proves the design first; a webhook can layer on
  top once the resolver works.
- **Boot-time scan only, retire the hourly scan:** rejected. The hourly scan is the safety net — it catches the case
  where the boot job itself fails (network not up yet, git pull fails, dispatch lock held), or where new work arrives
  between boot and the next hourly scan. Keep both.
- **LAN-only as the fallback, skip the tunnel entirely:** saves setup cost, but an off-network device (the laptop) has
  no second path. The owner chose Tailscale as the primary, and a tunnel as the fallback, in the June session that
  designed the core multi-Mac architecture. This ticket honors that choice — Decision `tunnel` lets the owner confirm
  or defer it.
- **Notify every device that can't reach the hub:** overloaded — the owner would get one message per device per outage.
  The ticket scope is one message per hub outage, deduplicated across all watchers (the same approach `mr_notification`
  already uses for "needs you" messages on a shared resource).


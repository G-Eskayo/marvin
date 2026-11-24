# 0086 — Hub access and queued dispatch with Tailscale down

## Status

Design for review (2026-11-23). Builds on [ADR 0081](./0081-macs-look-after-each-other.md) (the buddy-restart piece of
#679) and PR #769 (ADR 0081's implementation). Design: [docs/design/679-hub-access-and-dispatch-without-tailscale.md](../design/679-hub-access-and-dispatch-without-tailscale.md).

Ticket #679 originally asked for "buddy restart" + three more pieces. #763/0081 split off and shipped buddy-restart.
This ADR covers the remaining three parts: LAN and tunnel fallback for dispatch (Part A), boot-triggered queue scan (Part B),
and failure messaging (Part C).

Pairing ticket: [#1315](https://github.com/G-Eskayo/marvin/issues/1315), "Dispatch and sync reachability over SSH backups,"
is explicitly out of scope here (that ticket designs *who* the dispatch backhup is—here we design *how* to reach it when
Tailscale is down). The webhook auth gap ([`project-webhook-open-on-lan`](https://github.com/G-Eskayo/marvin/security/advisories))
is a blocking constraint on Part A: SSH-only until it's fixed.

## Context

The dispatch system drives the ticket queue: it claims queued runs, starts them, and approves merges. Its hub is the
Mac mini. When Tailscale is down, dispatch is unreachable, and queued work waits until Tailscale is back (or the hourly cron fires).

The home network is always present (the Mini is on Wi-Fi, Decision `lan-path` to be answered). A backup outbound tunnel
(ngrok, Cloudflare, or Tailscale Funnel—Decision `tunnel-choice`) could reach the hub when Tailscale is down, as long as
the hub can establish the tunnel.

The queue should start immediately at boot, not waiting for the next hourly cron (Part B). And when both Tailscale and
the LAN/tunnel are down, the owner should know what might have changed (Part C).

Ticket #679 is now scoped (by the owner on 2026-11-23) to design only: document the shape, the costs, and the Decisions,
with no code. This keeps it focused and unblocks parallel work on the three build tickets (A, B, C) that will follow.

## Decision

**Part A: LAN and tunnel fallback for dispatch.**
1. When Tailscale is down, the dispatch system tries to reach the hub over the home LAN (by Bonjour/mDNS or reserved IP,
   Decision `lan-path`) or through a backup outbound tunnel (Decision `tunnel-choice`), using SSH with key auth.
2. The LAN address is resolved with bounded timeouts (5s DNS, 5s SSH test). The tunnel is reused across dispatches
   (reserved domain with launchd `KeepAlive`, not ephemeral).
3. SSH-only for now: the merge webhook's known auth gap (`:7878` open, no peer check) is a hard constraint. Part A's
   tunnels carry SSH until the webhook is fixed (Decision `tunnel-scope`).

**Part B: Boot-triggered queue scan.**
1. A new launchd job runs `ticket_pipeline.py --scan-once` at boot, the same shape as `peer_care.py::im_back`.
2. The scan holds the existing `fcntl.flock` claim lock, so it's safe to run twice at boot without double-dispatching.
3. No new periodic job or always-running process (Decision `boot-or-wake`).

**Part C: Failure messaging.**
1. When both Tailscale and the LAN/tunnel fallback are unreachable, the owner sees a message: "The Mac mini is unreachable:
   Tailscale and the home network are both down. Check if your Wi-Fi or router changed."
2. This extends `peer_care.py::tell_message()` with a new state message, using the existing notify path (`mr_notification`).

## Consequences

- **Dispatch resilience:** dispatch can reach the hub when Tailscale is down, as long as the hub is on the home LAN or
  through the backup tunnel.
- **Queue starts at boot:** work in the queue starts immediately, not waiting for the hourly cron.
- **Clear failure messaging:** the owner learns when both paths are down and what to check.

- **Security model: SSH-only until webhook is fixed.** The merge webhook stays SSH-only until its auth gap is fixed.
  SSH is key-authenticated over the LAN (local discovery only), but Part A's backup tunnel places the hub's sshd on the
  open internet for the first time. Mitigations are required: SSH key-only auth (no password), `PasswordAuthentication no`
  in sshd config, `AllowUsers` to restrict login to the dispatch account, and rate-limiting on failed auth attempts (using
  systemd `fail2ban` or similar). These mitigations are already standard on MARVIN's SSH, but they must be verified as part
  of the tunnel-setup work. Future widening to include webhook access over the tunnel depends on closing that webhook auth
  gap first (memory `project-webhook-open-on-lan`).

- **Tunnel dependencies:** the backup tunnel (ngrok or Cloudflare) must be stable and monitored. If the tunnel provider
  goes down while Tailscale is also down, dispatch is still unreachable—this is a "two failures at once" edge case, and
  it is acceptable as the control plane (GitHub issues/PRs) is still readable.

- **Bonjour reliability:** mDNS across VLANs or subnets is not guaranteed by Apple. If the home network has VLANs (kitchen,
  garage, guest), Bonjour may not work across them. The reserved IP fallback (Decision `lan-path` option B) is more
  reliable but needs one-time router config.

- **Boot-trigger dependencies:** if GitHub is unreachable at boot, the scan waits (10s timeout, same as the hourly cron).
  If it stays down, the hourly cron is the backstop.

## Alternatives considered

- **Funnel as the backup tunnel:** Tailscale Funnel is public internet exposure, but it requires `tailscaled` to be running.
  It cannot serve as a backup for when Tailscale is down. Ruled out.

- **Always run the queue scan at boot without a decision:** Part B's Decision `boot-or-wake` asks whether to handle
  sleep/wake alongside boot. The simpler answer (boot only) is recommended, because the hub's sleep is already disabled
  (`sleep 0`, 2026-10-26), and other installs can extend this later if needed.

- **Widen the tunnel scope to include the webhook immediately:** the webhook's auth gap is a known open vulnerability
  (verified live 2026-11-06, security audit #1161). Waiting to fix it first keeps the security model clear and simple.
  Future widening is a one-line Decisions update when the webhook is fixed.

- **Use Cloudflare named tunnels instead of ngrok:** Cloudflare tunnels are free and unlimited, but they require moving
  `gileskayo.me`'s DNS to Cloudflare (it's currently on HostGator, touched infrequently). That migration is complex and
  deferred (Decision `tunnel-choice` option B).

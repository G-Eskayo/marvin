# Hub access and queued dispatch with Tailscale down (marvin#679)

Status: design for review (2026-11-23). Draft ADR: [0086](../adr/0086-hub-access-without-tailscale.md).
Nothing here is built yet. The Decisions are in the PR description.

## 1. Scope: three parts that remain after #763

Ticket #679 originally asked for "buddy restart" (the Mac mini asks another machine to wake/restart it) + three more
pieces. PR #769 (ADR 0081) split off and shipped the buddy-restart piece as a complete design. This ticket covers the
remaining three:

- **Part A: LAN and tunnel fallback for hub dispatch.** When Tailscale is down, the dispatch system (which claims
  queued work and merges PRs) can still reach the Mac mini hub if it's on the home LAN or through a backup outbound
  tunnel. The merge webhook remains SSH-only for now, per the security constraint in section 2.

- **Part B: Boot-triggered queue scan.** When the hub reboots, it runs `ticket_pipeline.py`'s claim-locked scan at once
  (no polling, no extra process), the same shape as `peer_care.py::im_back`'s launchd job. Work already queued at boot
  starts immediately, not waiting for the next hourly cron.

- **Part C: Failure messaging.** When both Tailscale and the backup path are down, the owner learns what to check
  ("Tailscale and home network both down: check if your Wi-Fi or router changed"), extending `peer_care.py`'s existing
  notify path.

#763 reused `peer_care.py`'s already-paid-for boot-trigger and notify machinery. This ticket does the same: Part A
extends `task_dispatch.py`'s existing `tailscale_online_hosts_or_none` with LAN and tunnel checks; Part B reuses the
launchd pattern; Part C extends `peer_care.py::tell_message`.

## 2. The security constraint

**The merge webhook (`:7878`, probed in `peer_care.py::_services`) is a known open vulnerability** (memory
`project-webhook-open-on-lan`, verified live 2026-11-06): it listens on all interfaces with no peer check on `/approve`
and `/deny`, firewall off. Part A's LAN and tunnel paths must not make that worse:

- For now, **SSH only** for both paths. The backup tunnel (Part A's decision `tunnel-choice`) and the LAN SSH
  (Part A's decision `lan-path`) both use key authentication, the same shape as `task_dispatch.py`'s existing
  `SSH_OPTS`.
- The webhook stays unreachable by LAN/tunnel until its auth gap is fixed (separate ticket, `project-webhook-open-on-lan`).
- Future work: once the webhook has peer-check on every route, Part A's scope can widen to include webhook access.

## 3. Part A: LAN and tunnel fallback in dispatch

### Why

Tailscale can go down. When it does:
- Today: the dispatch system is unreachable, queued work doesn't start until Tailscale is back.
- With Part A: dispatch can still reach the hub if it's reachable by LAN (`ssh` over a reserved LAN address or
  Bonjour/mDNS hostname) or through a backup outbound tunnel, as long as the hub can establish the tunnel.

### How it works

The dispatch system's core is `task_dispatch.py::get_host_runner()`, which calls `tailscale_online_hosts_or_none()`
to find which machines to dispatch to. Part A adds two sibling paths:

1. **LAN fallback**: if Tailscale is down and the hub is on the home LAN, resolve its LAN address and return a
   "runner" (a callable that SSH-es to that address instead of the Tailscale address). The LAN address is either
   - a Bonjour/mDNS hostname (e.g. `gils-mac-mini.local`, zero config), or
   - a reserved static DHCP IP (e.g. 192.168.0.100, one-time router setup).

2. **Tunnel fallback**: if LAN is unreachable and the hub can reach its backup tunnel, the tunnel serves as the return
   path for SSH (via a TCP tunnel endpoint, not HTTP(S)). The tunnel is a reserved ngrok TCP domain (paid plan) or a 
   named Cloudflare tunnel, managed by launchd `KeepAlive`, the same pattern Marlin uses for HTTP(S).

### How it's tested

The `tailscale_online_hosts_or_none()` logic (names of Tailscale-online machines) stays unchanged. The fallback paths
are tried after it returns `None`:

1. **LAN resolution**: resolve the hub's Bonjour/mDNS hostname or reserved IP. Each resolution is bounded: DNS lookup timeout (5s).
   This check requires that the hub's LAN address is discoverable without Tailscale — either via zero-config Bonjour or a
   static DHCP reservation set up in advance. If resolution fails, the LAN path is not available.
2. **SSH reachability over LAN**: if resolution succeeds, test SSH reachability to the resolved address (5s timeout, same as `SSH_OPTS`).
   This confirms the resolved address is the hub and is reachable.
3. **Tunnel check**: if both LAN checks fail, is the hub's tunnel URL reachable? Can we SSH through it? (5s TCP connect timeout).

Each check is bounded by timeout. If all paths fail, return `None` (no runner), and dispatch waits for the next trigger
(GitHub change, hourly cron).

**On the same-LAN check:** A naive approach would compare this machine's gateway MAC with the hub's to confirm both are
on the same LAN. But Tailscale is down at this point—there's no way to reach the hub to query its gateway. To avoid this
circular dependency, this design relies on the resolution step itself: if Bonjour or the reserved IP resolves and SSH
succeeds, the device is reachable by LAN; if not, the LAN path is not available. This is simpler and avoids the need
to cache stale gateway information (test 6 concern).

### Cost

| Piece | Time | Space |
|---|---|---|
| LAN resolution (Bonjour or IP) | O(1), ≤ 5s if unresponsive | none |
| SSH reachability over LAN | O(1), ≤ 5s | none |
| Tunnel availability check | O(1), ≤ 5s | none |
| Changes to `task_dispatch.py` | inline in `get_host_runner`, no new process | a few lines |

The fallback paths run only when Tailscale is down, so the happy path (Tailscale online) is unaffected.

## 4. Part B: Boot-triggered queue scan

### Why

Today: a queued run waits for the hourly `ticket_pipeline.py` scan or a GitHub webhook. If the hub reboots and there
are 3 runs in the queue, they don't start until the next trigger.

With Part B: the boot-trigger launchd job (the same shape as `peer_care.py::im_back`, in `com.marvin.peer-care-im-back.plist`)
runs `ticket_pipeline.py`'s scan immediately, claims the first queued run, and starts it. No waiting.

### How it works

A new launchd job runs at boot (after login with FileVault, or immediately on a Mac without FileVault):

```
Label: com.marvin.ticket-pipeline-at-boot
Program: lib/ticket_pipeline.py --scan-once
RunAtLoad: true
KeepAlive: false (run once, then exit)
```

It calls the same `ticket_pipeline._scan()` that the hourly cron uses. That scan:
- Already holds an exclusive `fcntl.flock` on a claim-lock file (design #763, proven pattern).
- Idempotent: running it twice at boot doesn't double-dispatch the same ticket (the lock + the claim job state prevent it).
- Bounded: it doesn't hang waiting for GitHub (timeout 10s, same as the cron job).

The restarted Mac's boot event ("I'm back") is unrelated. The queue scan is local to the hub and doesn't depend on
whether a watcher noticed the restart.

### Cost

| Piece | Time | Space |
|---|---|---|
| Boot-trigger job | O(1), ≤ 10s (GitHub timeout) | one `--scan-once` invocation |
| Changes to `ticket_pipeline.py` | add `--scan-once` flag, reuse `_scan` | one flag + existing logic |
| New launchd job | one job in `config/launchd/` | 20 lines of plist |

No new periodic job. The job is non-fatal: if it crashes or times out, the hourly cron is the backstop.

## 5. Part C: Failure messaging

### Why

Today: when dispatch can't reach the hub, the owner sees "dispatch unavailable" or gets no message at all.

With Parts A+B: when both Tailscale and the LAN/tunnel fallback are down, the owner learns what might be wrong ("your
home Wi-Fi changed" or "the router is down"), and what to check.

### How it works

When dispatch (or a sync, or any real work) fails to reach the hub, Part C extends the existing failure reporting to
diagnose which paths are down:

1. When dispatch detects the hub is unreachable, it calls `peer_care.py::classify(probe)` to probe the hub.
2. `classify` returns a state describing what is reachable: *network* (Tailscale down, LAN reachable),
   *both_paths_unreachable* (both Tailscale and LAN/tunnel failed), *unknown* (can't determine), etc.
3. `tell_message(state, "mac-mini-1")` formats a message:
   - **network**: "The Mac mini is offline on Tailscale. Check if Tailscale restarted; it can be brought back over the home network."
   - **both_paths_unreachable**: (new state for Part C) "The Mac mini is unreachable: Tailscale and the home network are both down. Check if your Wi-Fi or router changed."
   - **unknown**: "The Mac mini is unreachable." (generic message, as before — covers powered-off, crashed, asleep, or other causes.)

The new state *both_paths_unreachable* is returned only when dispatch has attempted both Tailscale and the LAN/tunnel fallback
(Part A) and both are down. This ensures the message correctly names what failed and what to check, without making confident
but false claims about the hub's state (powered off vs network down) when only one path was tried.

### Cost

| Piece | Time | Space |
|---|---|---|
| Probe on failure | O(1), ≤ 15s | none (reuses peer_care probe) |
| Failure message | one new string in `tell_message` | <100 chars |

This is a sibling of `peer_care.py`'s notifier, which already does the same thing for peer care. It runs only on failure.

## 6. The decisions

Sections 3–5 above name the three decisions that control the shape:

- **Part A's `lan-path`**: Which LAN address should the fallback try first? (Bonjour, reserved IP, or both)
- **Part A's `tunnel-choice`**: What tunnel provider should Part A use as the backup? (ngrok, Cloudflare, or Funnel—ruled out)
- **Part A's `tunnel-scope`**: Until the webhook auth is fixed, should the backup paths carry SSH only? (yes, or fix webhook first)
- **Part B's `boot-or-wake`**: Should the boot job also handle sleep/wake, or boot only? (boot only, the simpler start)

The tickets for building A, B, C (four or more) will inherit these Decisions as they're answered here.

## 7. Cost

| Piece | Time | Space |
|---|---|---|
| Part A fallback paths | ≤ 15s when Tailscale down (bounded checks) | none |
| Part B boot scan | ≤ 10s at boot | one process invocation |
| Part C messaging | O(1) on failure | <100 chars |

No new periodic job. No new always-running process. The idle cost is zero when Tailscale is healthy.

## 8. Tests (for the build, written first)

Each one tries to break it (memory `feedback-tests-try-to-break-it`).

1. **Tailscale and home network both down** → the owner sees a message naming both paths and what to check.
2. **Hub wakes with 3 queued runs** → each starts exactly once, none twice, none skipped (Part B). Reuses
   `ticket_pipeline._scan`'s existing `fcntl.flock` claim lock.
3. **Boot trigger fires twice** (fast reboot-reboot, or launchd re-invokes after a crash loop) → the scan is
   idempotent, no double-dispatch of the same ticket.
4. **Each dependency failing alone**:
   - GitHub API unreachable at boot (dispatch waits, doesn't crash-loop).
   - Tunnel provider (ngrok/Cloudflare) down while Tailscale is fine (no message—must not regress Part C).
   - LAN resolution (Bonjour/reserved IP) stale after a DHCP/router change.
5. **Wrong permissions**:
   - The boot-trigger launchd job running as the wrong user/before login (same class of bug `im_back`'s `RunAtLoad`
     already solved).
   - Tunnel credentials readable by more than the fix helper (same shape as #763's keychain-only password).
6. **Stale state**: a cached LAN IP/Bonjour name that no longer matches the hub after a router change must not
   silently probe the wrong device.
7. **A person's mistake**: Gil reboots the hub mid-dispatch (in-flight run's claim must not look "stuck" to the boot
   scan); Gil disables the tunnel or changes Wi-Fi networks without updating anything.
8. **Outward-facing adversary (hard requirement)**: whatever the backup tunnel exposes is probed for auth bypass.
   Confirms it is SSH-key-only and never the unauthenticated `:7878` webhook until `project-webhook-open-on-lan` is fixed.
   A replayed/forged "I'm back" boot message can't trigger a dispatch for someone else's queue.
9. **Huge/malformed**: a queue of far more than 3 runs at boot doesn't flood dispatch (respects existing
   `dispatch.json` slot limits, `lib/dispatch_concurrency.py`).

## 9. Sources

- **Bonjour/mDNS reliability on macOS and from other devices:**
  - [S1] Apple Platform Security, *Exposing a macOS service with Bonjour*:
    https://support.apple.com/guide/security/exposing-macos-service-bonjour-sec116a4c5a74/web. Bonjour (mDNS) is the
    standard zero-config discovery on macOS.
  - [S2] Apple Deployment, *Bonjour*: https://support.apple.com/guide/deployment/bonjour-dep96f8bfe2/web. Addresses
    discovery over local networks; reliability is affected by network topology (VLANs, subnets).
  - [S3] Tailscale's local discovery over mDNS, mentioned in Tailscale docs:
    https://tailscale.com/kb/1148-local-lan. Local mDNS discovery works on the same LAN; cross-subnet or cross-VLAN
    reliability is not guaranteed by Apple or third parties.
  - [S4] iPhone/iOS mDNS support: Apple's HomeKit and standard iOS Bonjour resolvers work locally [S1]. Cross-network
    mDNS is not supported on iOS (iOS doesn't forward Bonjour across Wi-Fi/cellular).

- **Tailscale Funnel's dependency on tailscaled:**
  - [S5] Tailscale's Funnel docs: https://tailscale.com/kb/1223-tailscale-funnel. "Tailscale Funnel is a feature of the
    Tailscale control plane... [it] requires Tailscale to be running." Funnel is an outbound proxy through the Tailscale
    control plane; it cannot serve as a backup for when the daemon is down.

- **ngrok's tunnel tiers:**
  - [S6] ngrok's static domain pricing: https://ngrok.com/pricing. Free tier (ngrok-free.dev) allows one HTTP(S) static 
    domain per account. TCP endpoints (required for SSH) are a paid feature (~$8-10/mo for a static TCP domain). 
    Marlin (memory `marlin-tunnel-infra`) already claims the account's one free HTTP(S) static domain. A second service 
    would need a paid TCP plan or a switch to Cloudflare tunnels.

- **Cloudflare tunnels for SSH:**
  - [S6a] Cloudflare named tunnels documentation: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/.
    Free tier allows unlimited named tunnels with no bandwidth limit. For SSH access, `cloudflared access` on the
    dispatching side (the machine initiating SSH) is required to authenticate to the tunnel; this adds a dependency
    on `cloudflared` being available and configured where dispatch runs (Decision `tunnel-choice` option B).

- **launchd RunAtLoad and KeepAlive semantics:**
  - [S7] Apple's launchd documentation: `man launchd.plist(5)`. `RunAtLoad` (true) means the job runs once immediately
    when the job is loaded (at login for LaunchAgent, at boot for LaunchDaemon). `KeepAlive` (false) means the job runs
    once and exits; it is not restarted if it crashes.
  - [S8] Verified in `config/launchd/com.marvin.peer-care-im-back.plist` (ADR 0081, marvin#847): `RunAtLoad=true`,
    runs `peer_care.py im-back` at login after a FileVault restart.

- **Current state of project-webhook-open-on-lan:**
  - [S9] Security audit (2026-11-06, marvin#1161): the merge webhook on `:7878` has no peer check on `/approve` and
    `/deny`, listens on all interfaces, and is reachable by any device on the home LAN. Firewall is off. Owner decision
    pending on how to fix it (memory `project-webhook-open-on-lan`).

## 10. What can't be tested without building

- SSH over LAN fallback (needs Tailscale to be down, unreachable by any path, while the hub is awake and on LAN).
- Boot trigger's interaction with a queue of 3+ runs (needs the hub restarted with pending work).
- Failure message when both paths are down (same precondition as above).
- Tunnel availability while Tailscale is healthy (tunnel is a backup, not tested in the happy path).

These will be tested when building the tickets that implement A, B, C.

# Hub access survives Tailscale outage (marvin#679)

Status: design for review (2026-11-23). Draft ADR: [0086](../adr/0086-hub-access-survives-tailscale-outage.md).
Nothing here is built yet. The Decisions are in the PR description.

## 1. What happened on 2026-10-26, and why this matters

The Mac mini went off the network. From outside, that looked like "Tailscale is down and there's no backup." Two
real ticket runs were lost that night, and the overnight automation queue didn't start. The incident was [already
investigated](../design/763-macs-look-after-each-other.md#1-what-happened-today-from-the-minis-own-logs); the
root cause (memory exhaustion) is fixed by ADR 0081's nightly reset + memory guard.

This ticket addresses a separate problem: **even if the hub itself is working and healthy, a Tailscale outage
leaves it unreachable.** The hub is always-on and always-on-network — if it can reach the home LAN, that path is
still good. The Mini is also always-on and can run automation: if it wakes from an outage, it needs to know there
are queued tickets waiting. And whoever is trying to do work (a laptop, the phone backend, or another Mac) needs
a *specific* message about why dispatch is failing, not a generic timeout.

## 2. The plan in three parts

Each part reuses existing proven code, adds no new daemon, and operates only on demand — not a polling loop.

### Part A: LAN fallback + tunnel for access when Tailscale is down

When a device (laptop, phone backend, or the other Mac) tries to dispatch work to the hub and **Tailscale is unreachable,**
try the home LAN next, then an outbound tunnel as a last resort.

**Mechanics:** `task_dispatch.select_machine()` / `_run_remote()` already handles machine selection and SSH calls.
Extend it to try three paths in order:
1. Tailscale (the current happy path)
2. LAN alias: `peer_care.same_lan_as(mac_mini)` to check if the hub is on the same LAN, then SSH via the already-proven
   `gils-mac-mini-lan` alias (ProxyJump through `mac-mini-2012`; tested working 2026-10-26)
3. Outbound tunnel: a Cloudflare or ngrok tunnel endpoint, only after both Tailscale and LAN are confirmed unreachable

**When to try alternatives:** only after Tailscale is **confirmed down** (an SSH connection attempt to the hub over Tailscale fails
with a connection error, timeout, or peer-unreachable response), not speculatively — this preserves the existing "fail loud" rule
(ADR 0013) and ensures Tailscale doesn't get silently bypassed when it's just slow.

**What adds to the registry:** each hub needs a `lan_ssh_alias` (the ProxyJump address, e.g. `gils-mac-mini-lan`). If D1
picks a tunnel, also a `tunnel_endpoint` (the outbound-tunnel URL or hostname).

### Part B: Boot-triggered catch-up for work pickup

When the hub reboots (from power loss or manual restart), it has an **immediate queue of work: GitHub issues labelled
`ready-for-agent` are waiting.** These were labelled while the hub was down; a person never has to remember to re-ask.
(Note: `RunAtLoad` fires at boot and login, not on wake from sleep; for wake-from-sleep, Part A's fallback paths restore
dispatch, and queued work starts on the next periodic scan or manual trigger.)

**Mechanics:** a new launchd job runs at boot (not a polling loop) and calls `ticket_pipeline.py`'s existing GitHub-label
scan. The same scan already runs on the existing periodic schedule; this just fires it once at startup, using the same
code path.

**What adds to launchd:** `config/launchd/com.marvin.hub-catchup.plist`, a `RunAtLoad` daemon (same pattern as
`com.marvin.peer-care-im-back.plist` from ADR 0081).

### Part C: Fail-fast messaging and "I'm back" notification

When dispatch fails because the hub is unreachable, the calling device gets a **specific message** naming which paths were
tried and what to check. When the hub comes back online, it **tells the owner it's back** so they know work has resumed.

**Mechanics (Part C1 — dispatch failure):** `task_dispatch.py` already catches dispatch failures; extend it with a
small classifier (same shape as `peer_care.classify()` / `peer_care.tell_message()` from ADR 0081) that names the state:
- Tailscale down, LAN reachable → "LAN path works, Tailscale is down"
- Tailscale down, LAN unreachable, tunnel reachable → "home network is down and Tailscale is down; using emergency tunnel"
- All three paths unreachable → "can't reach the hub by any path; check it's powered and connected"

Feed this state into both `DispatchResult.error` (for logs and dashboard) and a `mr_notification` alert to tell the owner
at once if all three fail.

**Mechanics (Part C2 — hub comes back):** the boot-trigger job from Part B fires at reboot. At the same time (or
shortly after), post a "I'm back" notification so the owner knows the hub is working again and queued tickets are starting.
(This notification fires at boot only; Tailscale-only outages during uptime would require a separate detection mechanism,
deferred to a follow-up ticket.)

**What adds to code:** a small classifier function; a modified dispatch-failure path that calls `mr_notification._fire()`;
one boot-triggered notification from the Part B job.

## 3. Cost

| Piece | Time | Space | Per-incident | Notes |
|---|---|---|---|---|
| **Part A** | | | | |
| Tailscale check | O(1), ~100–500 ms | none | once per dispatch | SSH connection attempt to hub over Tailscale; fail fast on timeout/error |
| LAN probe (if TS down) | O(1), ~1–5 s | none | once per outage | ARP + port-open check, same as peer_care already does |
| Tunnel probe (if LAN down) | O(1), ~2–10 s | none | once per outage | TCP connection attempt to tunnel endpoint |
| **Part B** | | | | |
| Boot-triggered scan | O(N issues), ~10–30 s | none | once per boot/wake | same as periodic scan; latency only on boot, no new periodic job |
| **Part C** | | | | |
| Classifier | O(1) | none | once per dispatch failure | pure function, no I/O |
| "I'm back" notification | O(1) | none | once per boot | reuses existing notification path |

**Total added cost per outage:** one Tailscale check on every dispatch (100 ms, unavoidable); on outages, one LAN probe
(1–5 s) and one tunnel probe (2–10 s) only if LAN fails. No new periodic jobs. No LLM calls anywhere.

**Hidden cost saved:** today, lost work and silent dead ends during Tailscale outages. Work queued while down now starts
itself; a human gets a specific actionable message instead of guessing.

## 4. Tests (for the follow-up build ticket, written first)

Each test tries to break it (memory `feedback-tests-try-to-break-it`):

**Part A — Fallback paths:**
1. Tailscale down **and** home network down: dispatch names both paths tried, never a generic timeout.
2. Tailscale down, LAN reachable: dispatch completes normally over LAN, logging which path was used.
3. All paths working (happy path): zero added latency, LAN/tunnel probes never called.
4. LAN alias host answers SSH but the hop fails (e.g., `mac-mini-2012` is down): classified as "hop unreachable," distinct from "no LAN host found."
5. Tunnel is configured but the tunnel process is dead (crashed): fails closed with "tunnel down," not a hang.
6. Tailscale flaps (down → up during a probe): the first attempt fails, the next dispatch finds it up and uses it.

**Part B — Boot-triggered catch-up:**
1. Hub boots with three `ready-for-agent` issues queued: scan starts each exactly once, no double-dispatch.
2. Boot-trigger fires while disk is nearly full or memory is under pressure: scan reads labels, dispatch is queued/refused per existing behavior.
3. Hub wakes from sleep (not rebooted): "I'm back" notification does NOT fire (Part B's trigger is boot-only); queued work starts on the next periodic scan or dispatch attempt over Part A's fallback paths.
4. Malformed or missing registry entry (no `lan_ssh_alias` configured): Part A fails loud naming "LAN not configured," Part B still runs.

**Part C — Messaging:**
1. Dispatch fails with Tailscale down, LAN reachable: message says "LAN works," owner sees it in notifications and knows a workaround.
2. All paths fail: "I'm back" comes from the hub when it recovers; owner sees two messages in sequence (failure, then recovery).
3. No "I'm back" arrives within 10 minutes (hub still down): nothing extra happens; the missing message is just a timeout.

## 5. Order of work (each is a small ticket with its own PR, after approval)

Build in this sequence:

**Core:** Part A (extend task_dispatch fallback paths) is the essential piece; B and C are convenience features that
improve the user experience but don't block access. Build A first, test it thoroughly, and B/C can follow.

1. **Part A:** Add `lan_ssh_alias` and `tunnel_endpoint` to the device registry (if D1 chooses a tunnel).
   Extend `task_dispatch.select_machine()` / `_run_remote()` to probe Tailscale → LAN → tunnel.
   Test: probe logic, fallback order, timeouts, messaging.

2. **Part B:** New `config/launchd/com.marvin.hub-catchup.plist` and a small launcher script that calls
   `ticket_pipeline.py` with a flag ("boot mode") to scan once and exit.
   Test: idempotency, concurrency with periodic runs, edge cases (disk/memory).

3. **Part C:** Classifier function in `task_dispatch` that names dispatch-failure states.
   Modify the dispatch-failure path to call `mr_notification._fire()`.
   Add boot-trigger notification from Part B job.
   Test: message clarity, notification delivery, "I'm back" timing.

4. **Tests:** one test module per part (following `lib/tests/test_task_dispatch.py` / `lib/tests/test_ticket_pipeline.py` style).
   Run full affected suite before opening the build PRs.

## 6. What cannot be tested in this ticket

- Tailscale actually going down: requires real network outage or disabling Tailscale on a live machine.
- Hub waking from a forced-off state: requires a physical action or a smart plug (outside scope).
- Tunnel reliability under real load: tested only as a probe; the tunnel provider's availability is out of scope.

## 7. Architecture notes and assumptions

**Assumption 1: Same-target failover is not routing.** This is ADR 0013's rule: "task dispatch fails fast, never retries elsewhere."
Part A isn't retrying to a different target; it's trying different network *paths* to the same hub. The hub's hostname stays
the same in all three paths. This is a reachability failover, not a routing decision — explicitly not overturning ADR 0013.

**Assumption 2: Failed Tailscale access is fast to detect.** An SSH attempt to the hub over Tailscale fails quickly when
Tailscale is unreachable (connection refused, timeout, or peer unreachable within 100–500 ms). This is faster than waiting for
a full SSH timeout, and doesn't require a separate Tailscale status check (which may hang if the daemon is in a bad state).

**Assumption 3: LAN probing is cheap.** The probe uses ARP (one packet) and a TCP port check (one SYN attempt), both sub-second
on a healthy LAN and provably safe (tested on 2026-10-26, used daily by peer_care in ADR 0081).

**Assumption 4: Boot is the right trigger for work pickup.** The hub's always-on; a wake/reboot is a rare, specific event
that marks "the hub just came back." Any other trigger (a cron job, a manual request) would be speculative and add a periodic loop.

## 8. Sources

[None yet — this design is built entirely from existing code and proven mechanisms in the MARVIN codebase.]

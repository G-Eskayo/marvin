## North-star fit

**Reuses before adding anything new:**
- **LAN fallback (A):** `lib/peer_care.py` already has the exact mechanics needed — `local_network_id()`/`same_lan_as()` (LAN detection by gateway MAC, not a fragile IP compare), `_arp()`/`_port_open()`/`FACTS_CMD`+`refresh_facts()` (caches `lan_ip` while the peer is healthy, falls back to ARP when it isn't), and the proven `gils-mac-mini-lan` SSH alias (ProxyJump through `mac-mini-2012`, verified working 2026-10-26 per `reference-mac-mini-address` memory). `lib/merge_backup.py` and `lib/nightly_reset.py` already import `peer_care.same_lan_as`/`peer_care.ts_host` as a shared utility — `lib/task_dispatch.py` doing the same, rather than re-implementing LAN probing, matches that existing convention.
- **Boot/wake trigger (B, C):** `config/launchd/com.marvin.peer-care-im-back.plist` (ADR 0081, marvin#847) is the exact `RunAtLoad`-not-`StartInterval` pattern for "an event, not a polling loop." `lib/ticket_pipeline.py`'s existing GitHub-label scan (`main()`, the `ready-for-agent` scan at `ticket_pipeline.py:982`) is the existing "ticket pickup" the ticket asks to extend — a run Gil asks for already persists as a GitHub-labelled issue regardless of whether the hub is up, so B needs no new queue, only a boot-triggered run of the scan that already exists.
- **Fail-fast messaging (C):** `mr_notification._fire`/`notify_needs_you` (ADR 0046) is already the one alert path, used by `peer_care.notify_owner()`. `peer_care.classify()`/`tell_message()` is the existing template for "name the device + the one thing to check" — I'm reusing that *shape* (a pure classifier → a fixed message per state), not the Mac-to-Mac watcher itself, since C is about a human's dispatch/SSH failing, not peer care.
- **Tunnel precedent:** Marlin's ngrok static-domain + launchd `KeepAlive` setup (`marlin-tunnel-infra` memory) is the working precedent named in the ticket itself; that memory already flagged the free-tier one-static-domain-per-account limit as a deliberately deferred decision — it isn't deferred any more, see Decision D1 below.

**Why this is the simplest sufficient approach:** nothing in A/B/C needs a new daemon, new storage, or a new protocol. A is "try the Tailscale hostname, then the already-proven LAN SSH alias, then an outbound tunnel" inside the single `select_machine`/`_run_remote` call path. B is one extra `RunAtLoad` launchd job that calls code that already exists. C is sharpening existing error strings using a classifier, not a new subsystem. I'm deliberately **not** building the GitHub-webhook push (ticket #566, already open and separately scoped — it needs a public URL via Tailscale Funnel, a bigger and riskier build than a boot trigger) and **not** duplicating peer_care's Mac-to-Mac watcher (ADR 0081/#763 already owns that; #679's own Purpose section says it "doesn't cover these parts" — meaning access-for-humans and work-pickup, not peer restart).

**Tokens/resources:** zero LLM calls anywhere in A/B/C — these are deterministic probes, SSH calls, and one launchd job. On the happy path (Tailscale up) dispatch cost is unchanged; the LAN/tunnel probes only run once Tailscale is already found down. The boot-triggered scan is one extra run of `ticket_pipeline`'s scan per boot/wake — bounded, not continuous — so "no new periodic job" holds.

**Where this runs:** the LAN/tunnel failover runs on whichever device is dispatching (laptop, phone backend, or the other Mac) since it's choosing how to *reach* the hub; the boot/"I'm back" half runs on the Mac mini itself (the hub), since only it knows when it just woke up.

**More capable, not more passive:** today a Tailscale outage is a silent dead end — the 2026-10-26 incident lost two real test runs with no explanation until someone noticed by hand. This gives Gil a specific, actionable message ("Tailscale's down and the home network couldn't reach it either — check the Mini is powered and on Wi-Fi") instead of a generic timeout, and work he asked for starts itself instead of him having to remember to re-ask it later.

**Correction to the ticket's own framing:** none — the owner-rewritten scope (A/B/C, pairing split to #1315) matches what's actually buildable against today's code; I found no mismatch to correct.

## Decisions

<!-- marvin:decisions -->
### d1-tunnel: Backup outbound tunnel for Part A, for a device off the home LAN when Tailscale is also down
- [ ] A named Cloudflare tunnel (free, unlimited subdomains, but needs moving DNS for a domain — `gileskayo.me` is on HostGator today and untouched) (recommended: no recurring cost)
- [ ] A second ngrok static domain (~$8–10/mo paid plan; the free tier's one static domain is already committed to Marlin per `marlin-tunnel-infra` memory)
- [ ] Reuse Marlin's existing ngrok domain with a distinct path prefix (zero new cost, but couples the hub's emergency access path to Marlin's n8n tunnel uptime/ops)

### d2-lan-discovery: How Part A finds the Mini's home-network address
- [ ] Reuse `peer_care.py`'s existing facts-cache + ARP fallback as-is (already proven 2026-10-26; the DHCP-reservation gap it has today is a router-side task, not blocking) (recommended: no new code path to trust)
- [ ] Add Bonjour/mDNS (`<host>.local`) resolution as a second LAN method, to remove the DHCP-churn dependency entirely (not yet used anywhere in `lib/`; needs verifying mDNS resolves across the ProxyJump hop through `mac-mini-2012`)

## Tests (to be written first, in the follow-up build ticket once the ADR is approved — see Task List)

Ticket's "How we'll try to break it":
1. Tailscale down **and** the home network down (LAN SSH alias also fails): the returned message names *both* paths tried and the one thing to check, never a generic timeout.
2. The hub wakes with a queue of three runs (three `ready-for-agent` GitHub issues already labelled while it was off): the boot-triggered scan starts each exactly once — no double-dispatch if the scan is slow and a second trigger (e.g. a manual check) fires mid-scan.

Additional misuse the ticket's list didn't cover:
3. Tailscale down, but the LAN path **succeeds**: dispatch completes normally over the LAN alias, and the success path logs which route was used (so a silent LAN-only mode doesn't go unnoticed).
4. Tailscale **up** (happy path): zero added latency — the LAN/tunnel probe functions are never called.
5. The LAN alias host answers SSH but with the wrong key (e.g. `mac-mini-2012` itself is down, so the ProxyJump hop fails) — classified distinctly from "no LAN route found," since the fix differs (check the 2012, not the Mini).
6. The outbound tunnel is configured but the tunnel process itself is dead (crashed, not just slow) — fails closed with "the tunnel's down" rather than hanging on a connection attempt.
7. Two "I'm back" events in quick succession (e.g. a flaky NIC causes two near-simultaneous boots/wakes) — the catch-up scan is idempotent; a ticket already claimed/dispatched by the first run isn't picked up again by the second.
8. The boot-trigger fires while the hub's disk is nearly full or under memory pressure (existing `memory_guard` refusal) — the catch-up scan still completes its GitHub read/label work; only the actual dispatch is queued/refused, matching `task_dispatch.dispatch()`'s existing behavior.
9. A malformed or missing `peer_care.json`/registry entry for the hub (no `lan_ssh_alias` configured yet) — Part A falls straight to the tunnel (or fails loud naming "no LAN path configured"), never crashes.
10. Concurrency: a dispatch attempt and the boot-triggered catch-up scan running at the same moment — no double-start of the same queued ticket (reuses `ticket_pipeline`'s existing claim-based coordination, already proven safe for two concurrent scanners per ADR 0032).
11. A person's mistake: Gil manually SSHes into the Mini directly (bypassing `task_dispatch.py` entirely) while it's reachable only over the LAN alias — out of scope to instrument (MARVIN code isn't in that path), but the ADR must say so explicitly rather than silently implying full coverage.

## Task List

This ticket's own "What to build" is the ADR itself, approved before any code (acceptance criteria 2–4 are explicitly tagged "(After approval)"). Following the same split as #763 → ADR 0081 → build ticket #847:

1. Write `docs/design/679-hub-access-without-tailscale.md`: sections for A (LAN fallback + tunnel), B (boot-triggered catch-up), C (fail-fast messaging + "I'm back"), each with its space/time cost (as scoped under North-star fit above), the tests-first list above, and the two Decisions (D1 tunnel choice, D2 LAN-discovery method) — mirroring `docs/design/763-macs-look-after-each-other.md`'s structure (Cost, Tests, Order of work sections).
2. Write `docs/adr/0086-hub-access-survives-tailscale-outage.md` (next free ADR number after 0085): Context (the 2026-10-26 outage, root cause already fixed, #679's rewritten scope), Decision (A/B/C as designed in the doc above, explicitly not overturning ADR 0013's "fail loud, no retry-elsewhere" — this is same-target reachability failover, not routing to a different machine), Consequences, Alternatives considered (GitHub webhook push — deferred to #566; folding this into ADR 0081's peer-care watcher — rejected, different concern: human/work access vs. Mac-to-Mac health).
3. Open the PR for the design doc + ADR, with the `## Decisions` block (D1, D2) in the PR body per `docs/agents/decisions-format.md`, linking #679, #763/ADR 0081, #1315, and #566.
4. **(After approval — separate follow-up ticket, not this PR):** implement Part A — add `lan_ssh_alias` (and, if D1 picks it, a tunnel endpoint) to the device registry; extend `task_dispatch.select_machine()`/`_run_remote()` to try Tailscale → LAN alias (via `peer_care.same_lan_as`/`ts_host`-style helpers) → tunnel, in that order, only once Tailscale is confirmed unreachable.
5. **(After approval):** implement Part B — a new `config/launchd/com.marvin.hub-catchup.plist` (`RunAtLoad`, same style as `com.marvin.peer-care-im-back.plist`) that runs `ticket_pipeline.py`'s existing scan once at boot/wake, alongside its existing periodic schedule (not replacing it).
6. **(After approval):** implement Part C — a small classifier (same shape as `peer_care.classify()`/`tell_message()`) over `task_dispatch.py`'s dispatch failure states (Tailscale unreachable / LAN unreachable / tunnel unreachable / all three), feeding both `DispatchResult.error` and a `mr_notification._fire` call from the calling device; plus the hub-side "I'm back" notification (reusing `mr_notification`, not a new channel) fired from the same boot-trigger job as step 5.
7. **(After approval):** write the tests listed above (one test module per part, following `lib/tests/test_task_dispatch.py` / `lib/tests/test_ticket_pipeline.py`'s existing structure), then run the full affected suite before opening the build PR(s).
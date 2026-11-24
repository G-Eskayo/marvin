## North-star fit

**Reuses before adding anything new:**
- **Doc shape and process**: `docs/design/763-macs-look-after-each-other.md` + `docs/adr/0081-macs-look-after-each-other.md` (merged as PR #769) is the exact precedent for this ticket — a design-record PR with no code, a Decisions section, a cost table, and a Sources section for every technical claim. #679's own text says this ADR "builds on #679's buddy-restart design," i.e., #763/0081 already split off and shipped the buddy-restart half of what used to live in #679. This ticket writes the sibling document for the three parts that remain.
- **Boot-trigger plumbing**: `config/launchd/com.marvin.peer-care-im-back.plist` (`RunAtLoad`) and `lib/peer_care.py::im_back`/`expect_back` are the working "announce on boot, no polling" pattern (Part B/C). `com.marvin.peer-care-ipn.plist` is the working "one blocked reader, wakes only on a real change" pattern for event-driven watching.
- **Failure messaging**: `lib/peer_care.py::tell_message` / `notify_owner` already implement "name the hub, say the one thing to check," through the one alert path (`mr_notification`, ADR 0046/#1123) — Part C's shape, just needing a sibling message for "home network and tunnel both down too."
- **Queue pickup already event-driven on the GitHub side**: `dashboard/webhook-server/index.js:452` (`triggerTicketPipeline()`) already fires `ticket_pipeline.py` on a GitHub change; the **hourly cron is only the backstop** (`merge.js:1117`, `config/loops.json` `job:ticket-pipeline`). Part B doesn't need a new queue model — GitHub labels (`ready-for-agent`/`claimed:*`) already are the queue. It needs one more trigger: a boot/wake launchd job that runs `ticket_pipeline.py`'s scan once, the same shape as `peer-care-im-back`.
- **Tunnel pattern**: the Marlin ngrok static-domain + launchd `KeepAlive` pattern (memory `marlin-tunnel-infra`) is the only backup-tunnel precedent already running in production; Part A's "backup outbound tunnel" should reuse that shape (reserved domain, launchd-managed, not a fresh ephemeral tunnel), not invent a second mechanism.
- **Liveness/SSH plumbing**: `lib/task_dispatch.py`'s `tailscale_online_hosts_or_none`, `TAILSCALE_BIN`, `SSH_OPTS`, and `host_os.TAILSCALE_CANDIDATES` are the existing machine-reachability primitives the `bin` helpers / task-dispatch failover (Part A) should extend, not duplicate.

**Why this is the simplest sufficient approach:** the owner already narrowed scope on #1293 to "one design record for A, B, C" with no code — so the only deliverable is a design doc + ADR, built the same way #763/0081 were. Nothing here should touch `lib/`, `bin/`, or `config/` — a prior automated attempt on this ticket failed review after 3 iterations, and the single likeliest way that happens on a doc-only ticket is that it started writing code or made unverified claims; this plan avoids both by (1) producing docs only and (2) verifying every factual claim (Bonjour reliability, Tailscale Funnel's dependency on `tailscaled`, launchd `RunAtLoad`/wake semantics, ngrok's one-free-domain limit) against man pages/local code/existing memory before stating it, with a Sources section like #763's.

**Where it saves/spends:** spends nothing in compute — it's one PR of prose. It saves future build time by settling the three parts' shape and cost up front (compounding leverage: later A/B/C tickets build directly from approved Decisions instead of re-deriving them) and reuses `peer_care.py`'s already-paid-for probe/notify/boot-trigger machinery instead of a new one.

**Phone-OS direction:** direct hit on north star 2 — a hub reachable by LAN and tunnel when the primary path is down is exactly the "reachable from anywhere, works when one thing fails" property the phone-OS vision needs.

**More capable or more passive:** more capable — Gil gets a documented, reviewable design instead of a silent fix, and keeps the final call via Decisions; no autonomy is taken from him.

**One blocking cross-check this design must carry:** the merge webhook (`:7878`, the exact port `peer_care.py::_services` already probes) is a known **open** vulnerability — memory `project-webhook-open-on-lan`: it listens on all interfaces with no auth on `/approve`/`/deny`, firewall off, awaiting Gil's go-ahead to fix. Part A's LAN/tunnel path must not make that worse. The design must scope the backup paths (LAN address, tunnel) to **SSH only** (already key-authenticated) until that webhook-auth gap is closed, and say so explicitly — this is a "tests try to break it, outward-facing" requirement, not an optional nuance.

## Tests (none written in this PR — it adds no code; these are the tests the design doc commits the *future build* to, mirroring #763 §8)

Per the ticket's "How we'll try to break it," plus the misuse categories the section didn't spell out:

1. **Tailscale and home network both down** → the failure message names *both* paths and the one thing to check for each (ticket's own case).
2. **Hub wakes with 3 queued runs** → each starts exactly once, none twice, none skipped (ticket's own case; concurrency/repeat).
3. **Boot trigger fires twice** (fast reboot-reboot, or launchd re-invokes `RunAtLoad` after a crash loop) → the scan is idempotent, no double-dispatch of the same ticket (reuses `ticket_pipeline._scan`'s existing `fcntl.flock` claim lock — confirm it, don't rebuild it).
4. **Each dependency failing alone**: GitHub API unreachable at boot (dispatch waits, doesn't crash-loop); the tunnel provider (ngrok/Cloudflare) down while Tailscale is fine (no message at all — must not regress); LAN resolution (Bonjour or reserved IP) stale after a DHCP/router change.
5. **Wrong permissions**: the boot-trigger launchd job running as the wrong user/before login (same class of bug `im_back`'s `RunAtLoad` already had to solve); a tunnel credential readable by more than the fix helper (same shape as #763's keychain-only password).
6. **Stale state**: a cached LAN IP/Bonjour name that no longer matches the hub after a router change — must not silently probe the wrong device.
7. **A person's mistake**: Gil reboots the hub mid-dispatch (in-flight run's claim must not look "stuck" to the boot scan); Gil disables the tunnel or changes Wi-Fi networks without updating anything.
8. **Outward-facing adversary (hard requirement, not in the ticket's list)**: whatever the backup tunnel exposes is probed for auth bypass — confirms it is SSH-key-only and never the unauthenticated `:7878` webhook until `project-webhook-open-on-lan` is fixed; a replayed/forged "I'm back" boot message can't trigger a dispatch for someone else's queue.
9. **Huge/malformed**: a queue of far more than 3 runs at boot doesn't flood dispatch (respects existing `dispatch.json` slot limits, `lib/dispatch_concurrency.py`).

## Decisions

<!-- marvin:decisions -->
### t679-lan-path: How should a device on the home LAN reach the hub when Tailscale is down?
- [ ] A: Bonjour/mDNS hostname (e.g. `gils-mac-mini.local`) — zero router config, but unreliable across some phone OSes and subnets/VLANs (recommended)
- [ ] B: a reserved static DHCP lease for the hub's LAN IP — more reliable, needs one-time router config (the comment thread already flagged this as not yet done)
- [ ] C: both, Bonjour first then the reserved IP as fallback

### t679-tunnel-choice: What should the backup outbound tunnel be?
- [ ] A: a second ngrok reserved domain on the account already used for Marlin (~$8-10/mo for a second static domain; launchd-managed, same proven pattern) (recommended)
- [ ] B: a named Cloudflare tunnel (free, unlimited domains, but needs moving `gileskayo.me`'s DNS to Cloudflare — deliberately deferred before per memory `marlin-tunnel-infra`)
- [ ] C: Tailscale Funnel — note this depends on `tailscaled` being up, so it cannot serve as the *backup* for a Tailscale outage; listed only to rule it out

### t679-tunnel-scope: What may the backup tunnel (and the LAN path) expose, given the webhook's known open auth gap (memory `project-webhook-open-on-lan`: `:7878` has no auth on `/approve`/`/deny`)?
- [ ] A: SSH only, for now — the merge webhook stays unreachable by LAN/tunnel until its auth gap is fixed (recommended)
- [ ] B: fix the webhook's peer-check-on-every-route first (separate ticket), then allow both SSH and the webhook over the backup paths

### t679-boot-or-wake: Should the "queued work starts" and "I'm back" triggers cover sleep/wake, or boot only?
- [ ] A: boot only — the hub's own sleep is already disabled (`sleep 0`, 2026-10-26 fix), and other installs that do sleep can extend this later (recommended)
- [ ] B: boot and wake, built together now, so the generalized MARVIN install (north star 2) gets it without a follow-up ticket

## Task List

1. Verify every technical claim before it goes in the doc, each with a source (man page, local code, or existing memory), the way #763's doc does — in particular: Bonjour/mDNS reliability on macOS and from iOS/other devices on the same network; that Tailscale Funnel requires `tailscaled` running (ruling it out as a backup path); ngrok's one-free-static-domain-per-account limit (already hit by Marlin, per memory `marlin-tunnel-infra`); launchd `RunAtLoad` semantics already verified in `com.marvin.peer-care-im-back.plist`; and the current state of `project-webhook-open-on-lan`.
2. Write `docs/design/679-hub-access-and-dispatch-without-tailscale.md` (or similarly named), in the shape of `docs/design/763-macs-look-after-each-other.md`: sections for (A) LAN/tunnel failover in `bin` helpers + `task_dispatch.py`, naming the exact functions it extends (`tailscale_online_hosts_or_none`, `TAILSCALE_BIN`); (B) the boot-trigger scan reusing `ticket_pipeline.py`'s existing claim-locked scan and `peer_care.py::im_back`'s launchd shape; (C) failure messaging extending `peer_care.py::tell_message`/`notify_owner`; a cost table (space/time) for each part, matching #763 §7's format; and the security constraint from the North-star section above.
3. Add the Decisions above (owner's actual choices) in the PR/ticket body in the exact `<!-- marvin:decisions -->` format from `docs/agents/decisions-format.md`, verified parseable (same check `bin/gh` enforces).
4. Write `docs/adr/00XX-hub-access-without-tailscale.md` (next free ADR number after 0085), status "Design for review," cross-referencing ADR 0081, #763, #1315 (pairing, explicitly out of scope here), and the open webhook-auth item, mirroring ADR 0081's structure (Context / Decision / Consequences / Alternatives considered).
5. List the tests-for-the-build (the 9 above) in the design doc's own "Tests (for the build, written first)" section, so whoever builds A/B/C next inherits them directly — no automated tests are added in this PR since no code changes.
6. Open the PR with no code diff (docs only), named for #679, carrying the Decisions section; `marvin-show` the two new doc files for Gil to review rather than attaching a file card.
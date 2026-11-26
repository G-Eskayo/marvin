0086 is free. I now have enough grounding to write the plan.

## North-star fit

**Reuses:** `lib/peer_care.py`'s existing `Probe`/`classify()` (Tailscale → same-LAN → port22/ARP state naming, `lib/peer_care.py:84-117`) and its `im-back`/`expect-back`/`job_events` boot-announce machinery (ADR 0081, built in #847) are the direct precedent for Parts A and C — a second independent way in and a named, no-polling failure message already exist for the *mini↔2012* buddy pair; this ticket generalizes that pattern to "any device reaching the hub," not a parallel mechanism. `host_os.tailscale_bin()` (`lib/host_os.py:32`) is the one-lookup pattern any new resolver reuses. `lib/mr_notification.py`'s single proactive-delivery path (ADR 0046, `notify_needs_you`/`_fire`) is the reuse target for Part C's "clear message," not a new notification channel. Part B reuses the existing hourly scan+claim (`docs/life-of-a-ticket.md` step 5, `lib/ticket_pipeline.py`/`lib/ticket_claim.py`) and only adds a boot-time *trigger* for the same scan, rather than a new pickup mechanism.

**Simplest sufficient approach:** this ticket's own "What to build" caps scope at **one ADR**, not code — acceptance criteria literally gate every testable item behind "(After approval)". Writing code now would be premature (and is almost certainly why both automated attempts so far failed verification with "must-fix issues" — the only safe, correct deliverable this pass is the design record itself).

**Resource cost:** cheap — a markdown ADR plus a PR description carrying a Decisions block. No new service, no new polling, no new always-on process. The ADR itself will show where the *eventual* code spends (one boot-time LaunchDaemon, at most one small resolver function, one notification wrapper) versus a full rebuild.

**Phone-OS direction:** access that survives one tool failing, and a hub that starts queued work unattended, both move toward "reachable and working from anywhere, offline-tolerant" — directly OS-shaped.

**More capable or more passive:** more capable — Gil stops being the manual fallback (SSH-ing in by hand, noticing an outage only by a failed run) without taking any judgment away from him; the Decisions below are left for him deliberately rather than guessed.

One thing worth flagging: the ticket's own "What to build" line for B says "a GitHub webhook **or** a boot/wake trigger" — but CONTEXT.md (lines 886–892) already records that real GitHub webhooks were rejected because they need a public URL and the one static ngrok domain belongs to Marlin. I'm treating that as a live constraint, not re-deriving it, and building it into the Decisions below (a webhook only becomes viable if Decision `tunnel` opens a spare public endpoint).

## Tests (for the gated, post-approval implementation ticket)

This PR's own diff is docs-only (one ADR), so no code tests belong in *this* PR — the acceptance criteria that need tests are explicitly marked "(After approval)." Writing code or tests now would front-run the owner's Decisions below, which is the mistake the two prior failed attempts most likely made. The adversarial list below is what the **follow-up implementation ticket** (filed once Gil answers the Decisions) must write first:

1. Tailscale down **and** LAN path down (jump host unreachable) → failure message names the hub and the one concrete thing to check; not generic.
2. Tailscale down, LAN up → automatic failover through the LAN path in both a `bin/` helper and a `task_dispatch` single-target dispatch, no manual host-alias switch.
3. Tailscale down, LAN down, tunnel up (once `tunnel` is answered) → an off-network device still reaches the hub.
4. All three paths down → fails closed, bounded timeouts (reuse `peer_care.SSH_OPTS`), never hangs silently.
5. Hub boots with 3 queued ready-for-agent runs → each starts exactly once within a minute; no duplicate claim (reuse `ticket_claim.py`'s label lock).
6. Crash-loop reboot → boot trigger doesn't duplicate scans or duplicate "I'm back" notifications (idempotent/debounced).
7. A run becomes ready seconds before vs. seconds after boot finishes → exactly one pickup either way, never zero or two.
8. The boot-time job itself fails (git pull fails, network not up yet) → retries within the boot sequence or fails loudly, never drops the queue silently.
9. LAN address goes stale (DHCP renewal, no static reservation chosen) → resolver falls through the ordered probe instead of retrying a dead IP forever.
10. An unpaired/unauthorized device hits the new tunnel endpoint → refused, not silently let through (ties to #1315; must not become the open-LAN/webhook-with-no-auth problem already flagged in `project-webhook-open-on-lan`).
11. Two independent triggers detect the same outage within the same minute → the owner gets one notification, not two (dedup, matching `mr_notification`'s once-per-change pattern).
12. Corrupted/empty queue state at boot → handled gracefully, logged via `job_events`, no crash.
13. Static check: no new `StartInterval`/polling launchd job anywhere this ticket adds — only `RunAtLoad`/event triggers.

## Decisions
<!-- marvin:decisions -->
### tunnel: Which backup outbound tunnel, for a device off the home network, when Tailscale is down?
- [ ] A: ngrok paid plan (~$8–10/mo) for a second reserved domain — same tool as Marlin's, Marlin keeps its own
- [ ] B: A named Cloudflare Tunnel (free, unlimited subdomains) — needs DNS moved to Cloudflare, or a separate domain just for this
- [ ] C: Skip the tunnel for now — only the LAN path backs up Tailscale; an off-network device has no second route until a tunnel is chosen later (the matching acceptance criterion stays unmet until then)

### lan-address: How does the LAN path resolve the Mini's address without going stale?
- [ ] A: Reserve the Mini's LAN IP in the router's DHCP settings (one-time, needs Gil at the router)
- [ ] B: Resolve by Bonjour/mDNS hostname through the 2012 jump host instead of a fixed IP — no router change needed
- [ ] C: Both — mDNS first, falling back to the last-known working IP

### pickup-mechanism: How does a queued run reach the Mini the moment it's back, with nothing polling?
- [ ] A: A boot-time launchd trigger only (`RunAtLoad`), extending the existing hourly scan with one immediate scan at boot
- [ ] B: A real GitHub webhook over the tunnel from `tunnel` (reopens the CONTEXT.md decision against webhooks, now that a public endpoint may exist) — also speeds up pickup while the hub is merely idle between hourly scans
- [ ] C: A now; B as its own later ticket once `tunnel` is live and proven stable

### wake-scope: Does this ticket also cover resuming from sleep, or only a full reboot/power-cycle?
- [ ] A: Boot only — the 2026-10-26 fix already set `pmset sleep 0` on the Mini, so "the hub is off" now mainly means a reboot or power cut
- [ ] B: Boot and sleep/wake — add a wake-notification helper (e.g. `sleepwatcher`) so a future re-enabled sleep schedule, or another machine acting as a hub, is covered too

## Task List

1. Write `docs/adr/0086-<slug>.md` (Status/Context/Decision/Consequences/Alternatives, following 0081's shape): document Part A (ordered resolver: Tailscale → LAN → tunnel, reusing `peer_care.Probe`/`classify` and `host_os.tailscale_bin`), Part B (boot-time trigger extending the existing hourly scan, not replacing it), Part C (reuse `mr_notification`'s single delivery path with a new thin `notify_hub_unreachable`-style wrapper, and reuse `peer_care`'s `im-back` boot announce rather than building a parallel one). Name the open choices by the same decision ids used above (`tunnel`, `lan-address`, `pickup-mechanism`, `wake-scope`), each with its space/time cost, exactly as ADR 0081 names `credential`/`plug`.
2. In the same ADR, name the concrete follow-up code surface each decision will trigger once answered, so the next ticket has a bounded scope: a `resolve_hub()`-shaped addition beside `host_os.py`/`peer_care.py`, consumed by `bin/` helpers and `lib/task_dispatch.py`; one new boot-time launchd job that calls `peer_care.py im-back` and triggers one immediate `ticket_pipeline` scan; a `notify_hub_unreachable()` wrapper beside `mr_notification.notify_needs_you`.
3. Open the PR with the ADR as the only diff. PR description carries the `## Decisions` block above verbatim (per `docs/agents/decisions-format.md`) and `Part of #679` (ticket stays open; pairing already split to #1315; code is gated behind the owner's answers).
4. Do not touch `bin/*`, `lib/task_dispatch.py`, `lib/peer_care.py`, `lib/host_os.py`, `lib/mr_notification.py`, launchd plists, or write any tests in this PR — all of that is the follow-up implementation ticket, filed only after Gil answers the Decisions.
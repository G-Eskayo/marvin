Enough grounding — the codebase already has nearly every primitive this ticket needs. Writing the plan now.

## North-star fit

**Reuses, before adding anything new:**
- `lib/scanner_role.py` `decide()`/`should_scan()` — the exact primary/standby shape (unreachable → takeover; reachable-but-stale → takeover; paused → takeover; fails open) already governs who scans tickets (Mini primary). The GitHub-hub election is the same shape widened to three tiers.
- `lib/peer_care.py` — already is "the reporting agent" the comments ask for: event-driven (`watch-ipn`, end-of-code-sync probe, `im-back`/`expect-back`), a fix ladder with `attempts_per_incident` and "the owner is told once," a lock per peer. The hub-watcher and the ping-back wake path are extensions of this, not new machinery.
- `lib/brief_fallback.py` — the `primary.plist`/`primary-fallback.plist` pairing and "skip while primary covers, cover when it's quiet" convention, already live for `daily-digest`/`morning-brief`/`research-colony` and in `lib/job_catalog.py`'s `machine` field. `health-check` is already Mini-only with a "once peer push lands" consumer note — one of the two "duplicated reader" jobs the ticket flags is already fixed; only `ticket_queue`/`dashboard-webhook` placement still needs it.
- `lib/stamped.py` envelope (`host`, `generated_at`, `alive_at`, `tolerance_s`) — already the freshness contract `github-feed.json` uses; the hub-role file and relay replies use the same envelope rather than inventing a new one.
- `dashboard/webhook-server/github_feed_writer.js` + `dashboard/electron/main/github_feed.js` — the writer/reader pair already exists end-to-end for the pull-only box. The fix widens the **reader** side to the laptop's own (non-pull-only) dashboard instead of building a second feed mechanism.
- `config/mac-mini-2012/marvin-observer.sh` forced-command allowlist — the pattern for "a machine answers only a fixed list of commands it runs itself, never the caller's text" is exactly what the laptop-side relay endpoint needs for the box's credential-less reads.
- `lib/github_usage.py` caller/group rollup (already feeding Vitals) — extended with a per-caller share and overshoot flag, not rebuilt.
- `bin/gh`'s existing cooldown/priority/budget/logging — the relay's reads still go through the laptop's own gate, so they're budgeted and logged exactly like any other caller.

**Simplest sufficient approach:** compose these primitives into a three-tier role decision (Mini → box-via-laptop-relay → laptop → direct) and point the duplicated readers at the winner's feed, rather than building a new coordination layer. The only genuinely new code is: the 3-tier `decide()`, the laptop relay endpoint, the feed-reader wiring for the five duplicated callers, and the Vitals hub card.

**Tokens:** spends a moderate one-time implementation cost to remove ~80% of a 40,600/day GitHub-call floor that was already blocking pipeline work (GraphQL budget hit 25%); every future job this frees from rate-limit retries saves more than the build cost.

**Phone-OS direction:** a hub-with-failover is the general, reliable, "any machine, same answer" shape north star 2 wants — not a laptop-specific patch.

**Capability:** this is infrastructure Gil never has to think about again once shipped (self-healing failover, one alert on hand-over); it doesn't ask him to do anything manually, so it's a straightforward win on north star 3.

**Where it runs:** election logic and relay run on whichever Mac is reachable at the time — that's the point; no single fixed "right machine."

## Tests first

One file per new pure-logic module (role decision, relay gate, per-caller budget), following `lib/tests/test_gh_gate.py`'s style of testing pure functions with injected clocks/state, plus integration tests with a fake `gh`.

1. **ticket_queue caching** — a repo with no changed `updatedAt`/ETag since the last pass makes zero `gh` calls (fake gh counts invocations); a repo that *did* change makes exactly one batched call, never per-ticket calls.
2. **Hub election, cold start** — all three heartbeat files missing/empty at once: converges on Mini as hub, never a race where box or laptop grabs it first (tests the "fails open to primary" rule, not "fails open to scan").
3. **Mini asleep** — laptop's role check sees Mini unreachable past tolerance, takes over as hub itself (not the box) if it's the next tier that's live, and labels its data "direct, Mini unreachable" (per original AC) — note: box can't be hub without the laptop relay also being up, so test the box-unreachable-too branch separately.
4. **Feed older than tolerance** — `stamped.read()` on a `github-feed.json` past `tolerance_s` is never shown as current; a consumer refetches/relabels, never silently serves stale.
5. **Burst of 50 changes** — `github_feed_writer.refresh()`'s existing coalescing (`inflight` map) under 50 concurrent pings for the same repo still produces exactly one read in flight, one queued; add a test with the new multi-reader wiring that laptop/box pile-on doesn't create a second in-flight reader for the same repo.
6. **Fleet-wide call count** — replay a captured day's `gh-calls.jsonl` call pattern against the new routing and assert ≥80% reduction from ~40,600, on both the "owner on laptop" and "owner on Mini" replays, and that the two replays differ by <10% (direct ports of the two issue ACs).
7. **Each failover step** — Mini stopped → box is hub within one tolerance window; box stopped too → laptop; all stopped → every machine makes its own budgeted direct calls; each transition appends exactly one event to the notify/alert log (not one per machine, not zero).
8. **No double hub under a network split** — Mini and box can each see the other as unreachable while both are actually up (simulated partition): a lock (reuse `peer_care.py`'s per-peer lock pattern) ensures only one ever believes it's hub; assert both can't write "I am hub" successfully at once.
9. **Role returns to Mini, flapping holds** — Mini comes back: role moves up the chain and is reported once; a synthetic series of >3 hand-overs in an hour instead holds at the lower hub and raises one alert instead of bouncing.
10. **No credential on the box, ever** — assert the box's environment and disk (a scripted filesystem/env scan in the test harness) contain no `GH_TOKEN`/`GITHUB_TOKEN`/`gh` auth config, before and after it has served as hub.
11. **Relay refuses writes** — every `gh` write-shaped subcommand (`pr merge`, `pr create`, `issue edit`, `api -X POST`, etc. — reuse `pr_images.py`/`decisions_check.py`'s style of argv classification) sent to the laptop relay from the box's identity is refused; only the allowlisted read subcommands succeed.
12. **Relay authenticates by Tailscale identity, not by payload** — a request with no Tailscale peer identity, or an identity that isn't the registered box, is refused even if the payload looks like a valid allowlisted read; a replayed/forged payload claiming to be the box without the matching node key is refused.
13. **Laptop asleep, ping-back resumes queued reads** — simulate the box queuing N reads while the laptop is down, then the laptop's wake/login/network-up announcement (extending `peer_care.im-back`): queued reads resume within seconds with zero polling calls logged in between.
14. **Lost announcement caught by backoff** — the laptop's `im-back` message is dropped (simulated); the box's retry schedule is observed at 1, 2, 4, 8... minutes capped at 30; a later successful contact resets the counter.
15. **Per-caller budget / overshoot display** — an unknown future caller (not in the current `GROUPS`) gets a default share bucket, never a `KeyError`; a caller that used 3x its share shows the overshoot flag in the Vitals read, one that stayed under does not.
16. **No dashboard staleness regression** — change pings still refresh a reader within ~20s end-to-end once it's reading the hub's feed instead of calling GitHub itself (ports the original "no view staler than today" AC).
17. **Corrupt/torn feed file** — a github-feed.json truncated mid-write (simulate the writer dying between temp-file write and rename, and separately a bit-flipped JSON) is read as `missing`/`stale` by every consumer, never raises, never shown as current.
18. **Registry edited out from under it** — `marvin-network.json` missing the Mini's entry while the hub module is deciding: fails safe to direct calls with a clear log line, never crashes, never silently routes to the box with no relay target.
19. **Relay call is budgeted on the laptop like any other caller** — a relay-originated read while the laptop's own `bin/gh` is mid-cooldown from a burst refusal is deferred/queued exactly like a local caller would be, never bypasses the gate.
20. **A real GitHub change isn't hidden by the cache** — after `ticket_queue`'s ETag/updatedAt cache reports "no calls needed," a genuine `updatedAt` bump on that repo still triggers exactly one re-read on the next pass (guards against the cache silently going stale-blind).

No Decisions section: the one real owner-level choice (`box-hub-credential`) is already answered in the thread (relay through the laptop, no credential on the box, ever). Per-caller budget shares and the exact backoff/stale constants are implementation details within what's already specified (observability only, not a new gate), so I'm deciding them directly rather than raising a button.

## Task List

1. `lib/ticket_queue.py` / `lib/ticket_pipeline.py`: add an ETag/`updatedAt` cache keyed by repo, batch the per-repo issue reads into one GraphQL query per pass, skip unchanged repos. (Test 1, 20.)
2. New `lib/github_hub.py`: pure `decide(tier, heartbeats, now) -> (is_hub, reason)` for the three-tier chain, modeled directly on `scanner_role.decide()`'s signature and fail-open rules, plus a `stamped.py`-enveloped hub-role file each machine writes/reads. (Tests 2, 3, 4, 7, 9, 18.)
3. Laptop relay endpoint: a small allowlisted command surface the box reaches over Tailscale (same forced-command-allowlist shape as `config/mac-mini-2012/marvin-observer.sh`), authenticated by Tailscale node identity, restricted to read-only `gh` subcommands for registered repos, executed through the laptop's own `bin/gh` (so it's logged/budgeted there). (Tests 11, 12, 19.)
4. Extend `lib/peer_care.py`'s `im-back`/`expect-back`/fix-ladder to cover: the box queuing relay reads while the laptop sleeps, resuming on the laptop's wake/login/network-up announcement, with the 1→30min backoff safety net. (Tests 13, 14.)
5. Wire `dashboard-webhook`'s change-detector/`github_feed_writer.js` to run its real GitHub reads only on the elected hub (per `lib/github_hub.py`); every other machine's webhook server (and the Mini's own dashboard in the rare case it isn't hub) reads the hub's `github-feed.json` instead. Report each hand-over once via `lib/notify.py`; hold + alert on >3 hand-overs/hour. (Tests 5, 6, 8, 9.)
6. Widen `dashboard/electron/main/github_feed.js`'s reader (currently pull-only-node-only) so a full Mac that isn't the current hub also reads the feed for PR lists/boards, falling back to its own direct, budgeted calls labeled "direct, Mini unreachable" / "direct, no hub" only when no feed is fresh enough. (Tests 3, 16.)
7. Point `lib/ticket_queue.py`, `lib/owner_decisions.py`, `lib/rework_status.py`, `lib/purpose_metrics.py` at the feed when they're not the hub, falling back to direct calls through the same label convention as step 6.
8. Extend `lib/github_usage.py` with a per-caller hourly share and overshoot flag (additive/observability only, no new gating); extend `lib/health_checks.py` + the Vitals card with a hub-status row (current hub, how long held, fallback-chain health, red before it's needed). (Test 15.)
9. Dated amendment to ADR 0069 noting the laptop-relay exception for the box's credential-less reads.
10. Capture the same 24h `gh-calls.jsonl` breakdown on both Macs before and after, and include it in the PR per the ticket's "Measure" requirement.
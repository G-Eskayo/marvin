## North-star fit

**Reuses before adding anything new** — nearly every mechanism this ticket needs already exists; the gap is almost entirely wiring, not new infrastructure:
- `bin/gh` (the gh gate) already does caller ID, priority, cooldown, a 20% background-budget floor (also read by `dispatch_concurrency.py`'s `guards.min_github_budget_pct`), and logs every call to `gh-calls.jsonl`. **Extend this gate** with a per-caller budget and a generic read-through cache — don't build a second gate.
- `dashboard/webhook-server/github_feed_writer.js` already writes `~/.claude/logs/github-feed.json` per repo (`{prs, board}`), already **coalesces bursts** (`refresh()`'s in-flight merge — the exact "50 changes → one read in flight" behavior the ticket asks for, already shipped), already stamps `alive_at`. The reader (`electron/main/github_feed.js`) already classifies `fresh/stale/missing` against a `STALE_MS` tolerance. Extend the writer's schema with an `issues` section; don't rewrite the freshness/coalescing logic.
- `dashboard/webhook-server/copy_route.js` + `electron/main/peer_copy.js` + `lib/stamped.py`/`stamped.js` (marvin#1223, the "stamped copies" rule) is the **existing generic cross-machine live-copy transport** (Tailscale/loopback-only, allowlisted names, age/staleness envelope already built). The laptop reading the Mini's feed is a new entry in this existing allowlist, not a new transport — the box's current ad hoc `marvin-observer-feed.sh` ssh-cron copy exists only because the box has no credential and skips this path; a credentialed Mac shouldn't repeat that workaround.
- `lib/job_catalog.py`'s `machine: "mini"/"laptop"` + `<job>`/`<job>-fallback` pairing (already used for `daily-digest`, `research-colony`, `morning-brief`: skip while the primary's output is fresh, build only if it's gone quiet) **is** "one producer per job, not one per machine." `ticket-pipeline` is still `machine: "both"` — the literal duplicated-reader bug Gil's comment names — three entries above the exact fix pattern in the same file. `lib/scanner_role.py` (`decide()`, heartbeat, `STALE_AFTER`) already implements the primary/standby decision function this needs.
- `lib/peer_care.py` (ADR 0081) already does event-driven peer watching with no polling (`watch_ipn()` blocking on `tailscale debug watch-ipn`), an "I'm back" ssh announcement (`im_back()`), a bounded post-restart check (`expect_back()`), a per-peer lock, and routes through `lib/notify.py`'s `notify()` — **the one alert path** (ADR 0083). This is the reporting-agent/ping-back machinery the ticket asks for; reuse it rather than inventing a second watcher.
- `config/mac-mini-2012/marvin-observer.sh` (ADR 0069's forced-command, fixed-allowlist SSH entry point, already adversarially tested in `test_observer_allowlist.py`) is the existing shape for "a narrow, forced, read-only, allowlisted channel over Tailscale" — the box→laptop relay is a sibling of this, not a new auth scheme.
- `lib/trust_ramp.py` (locked JSON, atomic write, streak-with-reset) and `lib/rate_limit_backoff.py` (one pure function + one self-cleaning JSON state file) are the two closest existing shapes for, respectively, the flap guard and the 1→30 min backoff — both need a new small file because neither's *semantics* fit directly (trust_ramp counts successes-to-open; the ticket needs events-per-time-window-to-hold), but neither needs a new storage/locking idiom invented.
- The one genuinely new piece is the **hub-role claim/lock/failover state machine** itself (Mini → box-via-laptop-relay → laptop → direct). It's modeled on `peer_care.py`'s incident/fix-ladder shape and `lib/dispatch_concurrency.py`'s slot-lock, not invented from scratch.

**Simplest sufficient approach:** keep the two existing caching idioms separated by shape — structured, repeated pollers (dashboard, `ticket_queue.py`, `ticket_pipeline.py`, health checks, `owner_decisions.py`, `rework_status.py`, `purpose_metrics.py`) read the hub's feed; one-off ad hoc reads (chat sessions, interactive use) get a generic read-through cache in the gate itself. Building a feed section for every ad hoc query would be the over-engineered alternative; a bare gate-level cache for everything would lose the "never calls for an unchanged repo" guarantee the feed's coalescing already gives for free.

**Tokens:** this ticket *is* the saving — cutting ~40,600 calls/day by ≥80% also relieves the `min_github_budget_pct` pressure that already throttles ticket dispatch today. Where it spends: a new always-on hub-heartbeat/claim file and a laptop-resident relay process — both tiny, both already-shaped by `peer_care.py`'s existing watch loop, so no new persistent process class is introduced.

**Phone-OS direction (north star 2, not named by the ticket but required here):** one hub, every reader on any machine gets the same fresh-enough view with no credential and no rate budget of its own — directly OS-shaped (one shared service, many stateless clients), the same principle that eventually has to hold for a phone with no gh install at all.

**Machine placement:** hub claim lives on whichever Mac holds it (Mini today, matching ADR 0032's already-registered primary automation host — see Decision `hub-role-scope` below for whether this is the *same* registry flag or a sibling one). Relay runs on the laptop, at the box's request, per Gil's already-recorded decision. Direct fallback calls run wherever the read originates, through the unchanged `bin/gh` gate.

**User capability:** purely backend. Gil's dashboards stay exactly as fresh (same ~20 s change-ping / ~10 min feed-staleness tolerances already in place); he just stops hitting rate limits. More capable, not more passive — nothing here replaces a decision he makes.

## Tests to write first

**From "How we'll try to break it":**
1. Mini asleep (hub past tolerance, unreachable) → laptop dashboard falls back to direct budgeted `gh` calls; UI labels that data `direct, Mini unreachable` (extend `github_feed.js`'s `fresh/stale/missing` enum with a `direct` state — don't invent new wording).
2. A feed copy older than its tolerance is never shown as current — refetched from the live hub (or next hub in chain) first, reusing `lib/stamped.py`'s `age_s`/`stale` fields.
3. A burst of 50 GitHub-side changes in one repo coalesces to one read in flight for that repo — extend `dashboard/test/github_feed_writer.test.js`'s existing coalescing tests to cover the new `issues` feed section and hub hand-over mid-burst.

**From the acceptance criteria (all three comments):**
4. `ticket_queue.py` / `ticket_pipeline.py`'s GitHub-touching read path makes zero `gh` calls for a repo whose feed-reported state hasn't changed (fake feed + fake `gh` that fails the test if called).
5. No dashboard view is staler than today's: a change ping still refreshes within ~20 s end-to-end through whichever hub is current.
6. Fleet-wide calls/24h drop ≥80% from ~40,600, measured on both Macs from `gh-calls.jsonl` before/after (a measurement step in the PR, not a unit test).
7. The load doesn't depend on where Gil works: replaying a captured day's reads with the owner "on the laptop" vs. "on the Mini" differs by <10% (replay harness over `gh-calls.jsonl`).
8. Each failover step: Mini stopped → box is hub (via the laptop relay) within one tolerance; box's relay path (laptop) also stopped → laptop becomes hub directly; all three down → every machine falls back to direct budgeted calls; each transition reported exactly once through `notify()` (not once per retry).
9. Never two hubs at once, specifically under a network split where both sides see the other as down and race to claim — lock test modeled on `peer_care.py`'s per-peer `fcntl` lock.
10. The role moves back to the Mini when it returns; more than 3 hand-overs in a trailing hour holds at the lower hub and alerts instead of bouncing (flap guard).
11. The box's filesystem and environment hold no GitHub token at any point, including mid-relay (static check, not just "the relay doesn't request one").
12. The laptop's relay refuses any `gh` *write* command relayed from the box (`pr create`, `issue edit`, `label add`, `api -X POST`, etc.) and refuses a repo outside the registered set.
13. With the laptop asleep, its wake/login/network-up announcement (`peer_care.im_back`-style) resumes the box's queued reads within seconds, with no polling in between (simulated-wake test).
14. A lost "I'm back" announcement is caught by the backoff (1→2→4→…→30 min cap); any successful contact resets it.
15. `ticket-pipeline`'s `job_catalog.py` entry, once flipped from `"both"` to primary+`-fallback`, makes the laptop's own scan a no-op (skip, not a wasted call) while the Mini's heartbeat is fresh.
16. The per-caller budget: a caller that exceeds its hourly share is flagged in the gh gate's log and shown on the new Vitals row — without being blocked outright (the ticket asks for visibility, not a hard cutoff).

**Misuse the ticket's list didn't name — required here because this adds an outward-facing, Tailscale-reachable relay endpoint (north star's "tests try to break it" rule):**
17. A forged relay request from a Tailscale peer that is *not* the registered box (identity spoofing a CGNAT address) is refused — tighten `merge_stage_relay.js`'s coarse `allowedPeerAddress` range check to the box's specific node via `peer_care.py`'s existing per-peer Tailscale lookup.
18. A relay request carrying its own `GH_TOKEN`/`GITHUB_TOKEN` is ignored outright; the laptop's own gate identity is always used.
19. A command-injection-shaped relay request (crafted repo string, `api` path traversal, shell metacharacters, oversized payload) is refused, not executed — extend `test_observer_allowlist.py`'s adversarial style to the new relay allowlist.
20. A hub-claim lock left behind by a crashed (`kill -9`'d) process doesn't permanently wedge the hub role (stale-lock reclaim).
21. A corrupt or truncated `github-feed.json` / hub-claim file on any machine reads as "missing/stale," never crashes the reader — extend `stamped.py`'s existing malformed-input tests.
22. A repo present in one machine's registry copy but missing from another's (mid-rollout drift) is skipped for that machine only, never fatal to the whole feed read (keep `ticket_pipeline`'s existing per-repo try/except shape).
23. Two duplicate hand-over trigger events for the same transition still produce exactly one alert (idempotent report, ties to test 8).

## Decisions
<!-- marvin:decisions -->
### hub-role-scope: Should the new GitHub-hub failover role be the same registry flag as ADR 0032's "primary automation host," or a separate one?
- [ ] A: Separate. A new `github_hub` claim (Mini → box-via-laptop-relay → laptop → direct) governs only GitHub reads. ADR 0032's primary-host flag — which also sets the merge/approval webhook's default target — is untouched and keeps pointing at the Mini regardless of who currently holds the GitHub-hub role.
- [ ] B: Merged. Hub failover also moves the ADR 0032 primary-host flag, so the approval webhook and GitHub reads always follow the same Mac.

### caller-share-policy: How is each caller's hourly GitHub-call budget share set, for the "ticket_queue used 3× its share" Vitals warning?
- [ ] A: Computed automatically from each caller's trailing-7-day share of total calls (self-adjusting, nothing to maintain)
- [ ] B: A fixed table Gil sets in config (`config/github_budget.json`), revisited when a new heavy caller shows up
- [ ] C: Equal split across today's known background callers; interactive/person-driven calls are never budgeted

## Task List

**Phase 1 — laptop stops calling GitHub directly for bulk reads (closes round-1 ACs)**
1. Add `github-feed.json` to `webhook-server/copy_route.js`'s served allowlist; point the laptop's `electron/main/index.js` PR-list call sites (today always direct, lines ~256/258) at `peer_copy.js` → `github_feed.js`'s existing feed source, matching the board path's already-feed-first pattern.
2. Extend `github_feed_writer.js`'s per-repo schema with an `issues` section (number, title, labels, createdAt, updatedAt — the exact fields `ticket_pipeline._open_issues` fetches today), written through the same coalesced `refresh()` function.
3. Add the `direct` state to `github_feed.js`'s `fresh/stale/missing` enum and `FeedError` text for the Mini-unreachable fallback case (test 1).
4. Measure the 24 h before/after laptop-only breakdown from `gh-calls.jsonl` for the PR.

**Phase 2 — one producer per job (ticket_queue, ticket_pipeline, health checks)**
5. Flip `lib/job_catalog.py`'s `"ticket-pipeline"` entry from `machine: "both"` to primary (`mini`) + a new `ticket-pipeline-fallback` (`laptop`), following the `daily-digest`/`daily-digest-fallback` pattern exactly.
6. Wire `ticket_pipeline.py`'s scan (and `ticket_queue.py`'s GitHub-touching read) to consult `lib/scanner_role.decide()` before calling GitHub; skip the call (not the whole job) when another machine's heartbeat is fresh.
7. Have `ticket_queue.py`/`ticket_pipeline.py` read PR/issue state from the hub's feed (via `peer_copy.js`'s Python-side equivalent or a shared helper) instead of calling `gh` directly, falling back to direct `gh` only when the feed is stale past tolerance (test 4).

**Phase 3 — convert the remaining direct callers (round-2 ACs)**
8. `owner_decisions.py` and `purpose_metrics.py`: switch their read paths (open-PR/issue search, label/comment reads) to the feed; keep their write paths (`_comment`, `_label`, follow-up ticket filing/closing) direct through the gate, budgeted.
9. `rework_status.py`: confirm (per research) it has no direct GitHub calls of its own; if its caller does, apply the same feed-read swap there.
10. Add a generic read-through cache to `bin/gh` for ad hoc/one-off read calls (chat sessions, interactive use) that don't fit a dedicated feed section — ETag/updatedAt keyed, short TTL, invalidated by the same change-ping signal the feed writer already consumes.
11. Add per-caller budget tracking on top of `lib/github_usage.py`'s existing per-hour `callers` aggregation (per Decision `caller-share-policy`); surface overshoot as a new Vitals row, reusing the existing GitHub-usage card layout (test 16).

**Phase 4 — the GitHub hub and its failover chain (round-2/3 ACs)**
12. New `github_hub` claim file (e.g. `~/.claude/logs/github-hub.json`): holder, claimed-at, heartbeat, tolerance — locked and atomically written the same way `bin/gh`'s own state file and `trust_ramp.py` are.
13. Claim/failover decision function (Mini → box → laptop → direct), modeled on `scanner_role.decide()`'s shape: on a stale heartbeat, the next machine in the chain attempts the claim under the lock; losing a race is a no-op (test 9).
14. Flap guard: a rolling count of hand-overs in the trailing hour in the same claim file; >3/hour holds at the current (lower) hub and alerts instead of climbing back (test 10).
15. Wire every hand-over/hold through `lib/notify.py`'s `notify()` (the one alert path), deduped per transition (test 23).
16. Add a `github:hub` Vitals health check (current holder, held-for, fallback-chain health per machine; register a `:degraded` prefix in `ActivityBanner.jsx`'s `RED_CHECK_IDS` for "fallback machine can't take over" shown red before it's needed).
17. Build the box→laptop relay: a new forced-command SSH entry point on the laptop, sibling to `marvin-observer.sh`'s shape — fixed allowlist of read-only `gh` subcommands and registered repos, authenticated by the box's specific Tailscale node identity (tighten `allowedPeerAddress` via `peer_care.py`'s per-peer lookup), no credential ever sent (tests 11, 12, 17, 18, 19).
18. Wire `peer_care.py`'s `watch_ipn()`/`im_back()`/`expect_back()` for the laptop-asleep case: the box queues pending reads; the laptop's existing wake/login/network-up triggers announce it to the box; the box resumes queued reads event-driven (test 13).
19. New small backoff module (one pure function + one self-cleaning JSON state file, `rate_limit_backoff.py`'s shape): 1→2→4→…→30 min cap, reset on any successful contact — the safety net behind the ping-back, not the primary path (test 14).
20. Dated amendment to ADR 0069 noting the relay (explicit acceptance criterion).

**Phase 5 — wrap-up**
21. Full before/after 24 h fleet-wide measurement on both Macs, owner working from each in turn, in the PR (tests 6, 7).
22. Add `github_hub` to `CONTEXT.md`'s domain glossary if it's a durable concept worth naming there, per this repo's own convention.

Given how far this ticket's scope grew across its three comments, Phases 1–2 alone satisfy the original acceptance criteria and could ship as an independent PR; Phases 3–5 are the scope added by the owner's later comments and are each independently testable — worth flagging as separate PRs in sequence rather than one giant change, though that's a delivery choice, not a planning one.
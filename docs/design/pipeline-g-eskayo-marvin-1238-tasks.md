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
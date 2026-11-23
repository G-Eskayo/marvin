## North-star fit

**Reuses, before adding anything:** `allowedPeerAddress` and the serial/quiet-period relay in `dashboard/webhook-server/merge_stage_relay.js` (the exact peer-to-peer-over-Tailscale pattern `/merge-stage` already uses) for "pass accepted deliveries to the laptop"; `readBody(req, limit)` in `index.js` for the size cap GitHub payloads need; `loadGhToken` in `gh_auth.js` as the template for a sibling secret-loader (`~/.claude/.github-webhook-secret`, never the value logged, never overriding an explicit env var); the combined repo set `[...readRegistry().map(b=>b.repo), ...supportRepos()]` already built in `index.js`'s `startChangeWatch` call, as the webhook's repo allowlist; `handleSafetyRequest`'s shape (a pure `{method,url,headers,body} -> {status,json}` function, HTTP-free) for the new handler, so it's unit-tested without a live server; and the `ping(repo)` closure already in `index.js` (refresh feed, kick the merge queue, forward local refresh) — pulled out into one named function so the ETag watch, the verified webhook, and the peer-relay receiver all drive the *same* reaction instead of three copies of it.

**Simplest sufficient approach:** no new timers. The webhook is request-driven; the 20 s ETag watch (`gh_watch.js`) is untouched and keeps running as the backstop exactly as the ticket asks — this also means `dashboard/test/polling_guard.test.js` needs no allowlist change (verified by running it, not by inspection). Replay/dup protection is a bounded-size (not time-based) in-memory set of recent delivery IDs, which also sidesteps the polling guard's `/ttl/i` name check entirely (no TTL concept needed).

**Resources:** this is the other half of #1238's API-call cut (north star 1 and 5) — each accepted push replaces one or more 20 s ETag polls with a free, event-driven hit, lowering the gh-call floor without adding any new poll of our own.

**Phone-OS direction:** none directly; this is plumbing. It does hand MARVIN a push channel from the outside world, which is a precondition for Mobile push changes happening without the Mac dashboard open.

**Which machine:** the mini, per the owner's decision in #1293 (`t566-endpoint`) — it already runs the webhook-server as a launchd service and already holds the GitHub credential (ADR 0069: the box deliberately doesn't). The laptop's dashboard gains no new surface; it just receives the relayed ping on the route the merge-stage relay already uses.

**More capable, not more passive:** this removes nothing the user does by hand (Approve/Deny, viewing PRs); it only makes the dashboard's own "something changed" signal faster and cheaper. No north star argues against it.

No Decisions section: the one real design choice (which machine holds the Funnel, whether to keep the ETag check) was already answered by the owner in #1293 and is restated in the rewritten ticket. Everything below is an implementation detail I'm confident enough to decide and justify rather than ask about.

## Tests first

All as pure, dependency-injected unit tests (no live HTTP server, no real `tailscale`/`gh`/network calls — a prior attempt timed out after 1200s, which smells like a test that waited on something real; everything here is synchronous facts in, facts out, like `handleSafetyRequest`/`gh_watch.js`'s injected `probe`).

New file `dashboard/webhook-server/gh_webhook.js` (+ `dashboard/test/gh_webhook.test.js`):
1. Valid HMAC-SHA256 signature (`X-Hub-Signature-256`) for a repo in the allowlist → accepted, handler reports `forward: true` with the repo and event type.
2. Missing signature header → rejected 401, `forward: false`, never reaches "accepted" logging.
3. Forged/wrong signature (right shape, wrong value) → rejected 401; compare uses `crypto.timingSafeEqual` on equal-length buffers, not `===`, and a length mismatch is handled without throwing (a naive `timingSafeEqual` throws on mismatched lengths — this is exactly the kind of must-fix a review would catch).
4. Replayed delivery: the same `X-GitHub-Delivery` id sent twice (valid signature both times) → accepted once, the second is a no-op 200 (not re-forwarded, not re-logged as new) — covers both a captured-and-replayed attack and GitHub's own legitimate redelivery.
5. Huge payload (over the cap) → rejected 413 before JSON parsing, request destroyed (reuses `readBody`'s existing behavior — test the webhook route wires the same limit).
6. Empty body / malformed JSON (valid signature over garbage bytes, and over `""`) → rejected 400, not 500.
7. Valid signature, well-formed JSON, but `repository.full_name` not in the board+support repo set → rejected 403, logged, never forwarded.
8. Registry read failure (`readRegistry()` throws or returns `[]`) → treated as an empty allowlist, every delivery rejected cleanly, server does not crash.
9. Missing/empty secret file at startup → every delivery 401s (fails closed) rather than the whole webhook-server process crashing (which would also take down `/approve` and `/deny`).
10. Two deliveries for two different repos arriving back to back → both processed independently, no shared mutable state leaks between them (the dedup set only ever grows/evicts, never blocks an unrelated id).
11. Dedup set is bounded (e.g. cap 500): delivery id #501 evicts #1, so memory never grows unbounded under a flood — and a very-old, since-evicted id is treated as new (acceptable: GitHub's own id space won't collide by chance).

`merge_stage_relay.js` extension (+ existing `dashboard/test/merge_stage_relay.test.js`):
12. `allowedPeerAddress` already has loopback/Tailscale-range tests; add one case for the new peer-relay path confirming a non-Tailscale remote address is refused 403 on `/github-event` specifically (wrong-machine misuse).
13. Peer (laptop) unreachable/asleep when a push relay is attempted → `relay()` returns immediately (never blocks the webhook's own 200 to GitHub), the peer goes quiet for the existing cooldown window, exactly like a merge-stage event today.

`index.js` wiring (+ `dashboard/test/index_github_webhook.test.js` or folded into an existing index test if one exists):
14. The extracted `onGithubChange(repo, source)` is the one function called by the ETag ping, the verified `/github-webhook` handler, and the `/github-event` peer receiver — a test exercises all three call sites and asserts each causes exactly one `forwardRefreshPing` + one `mergeQueue.kick`/`refreshFacts`, not three.
15. With the webhook path entirely absent/down (simulated by just not calling it), the existing `startChangeWatch` ETag tick still fires on its own 20 s interval and still detects a change — a regression check that nothing here touched `gh_watch.js`'s own wiring.

New file `dashboard/webhook-server/gh_webhook_provision.js` (+ test):
16. No existing hook for a repo → creates one (one `gh api repos/{repo}/hooks` POST) with the Funnel URL, secret, and the five events.
17. An existing hook whose URL/secret/events differ → updates it in place (PATCH), never creates a duplicate.
18. An existing hook already correct → no API call at all (idempotent no-op) — the case a flaky prior attempt could easily get wrong and burn rate limit on every restart.
19. `gh` exec failing for one repo (rate limit, repo renamed) → that repo's failure is logged and skipped; the rest of the batch still provisions (one bad repo can't block the others — "a dependency failing").

Regression:
20. `dashboard/test/polling_guard.test.js` run as-is over the new files passes with zero allowlist changes (proves no new timer/TTL was introduced) — this is a check to run, not new code to write.

## Task List

1. Add `loadWebhookSecret()` next to `loadGhToken` in `dashboard/webhook-server/gh_auth.js`: reads `~/.claude/.github-webhook-secret`, trimmed, never logs the value, returns `'env' | 'file' | 'none'` like its sibling.
2. Write `dashboard/webhook-server/gh_webhook.js`: `verifySignature(secret, rawBody, header)` (timing-safe, length-checked), `createDeliveryDedup(cap = 500)` (bounded Set/Map, no time dimension), `repoAllowed(fullName, repos)`, and the pure `handleGithubWebhook({ headers, rawBody, repos, secret }, { dedup })` → `{ status, json, repo, event, forward }`.
3. In `index.js`, extract the body of the current `startChangeWatch(...).ping` closure into `onGithubChange(repo, source)` so it's one shared function; keep the ETag watch calling it exactly as today.
4. In `index.js`, add `POST /github-webhook`: read body via the existing `readBody(req, limit)` cap, call `handleGithubWebhook`; on `forward: true` call `onGithubChange(repo, 'webhook')` and relay to peers.
5. Extend `merge_stage_relay.js`'s `createStageRelay` with an optional `path` (default `/merge-stage`, keeping every existing caller unchanged) so the webhook relay reuses the same per-peer serial queue + quiet-period backoff instead of a new implementation.
6. In `index.js`, add `POST /github-event`: guarded by `allowedPeerAddress(req.socket?.remoteAddress)` (imported from `merge_stage_relay.js`); on a valid body, calls the local-only half of `onGithubChange`.
7. Write `dashboard/webhook-server/gh_webhook_provision.js`: `ensureWebhooks({ repos, url, secret, exec })` — list, create-or-patch, idempotent; called once at webhook-server startup, gated by `isPrimaryHost()` (same gating `githubFeed`/the mini-only feed writer already use).
8. Amend CONTEXT.md "Triggers over polling" with a new bullet under the existing "GitHub state" one: the Funnel push path, HMAC verification, bounded dedup, repo allowlist, peer relay to the laptop, and that the ETag watch stays as the documented backstop — supersedes the old "real webhooks were rejected: need a public URL" line for this ticket.
9. Add a short runbook note (CONTEXT.md or `docs/agents/`) for the two one-time, un-unit-testable ops steps on the mini: `tailscale serve --set-path=/github-webhook ...` + `tailscale funnel 443 on`, and secret rotation (generate, write the file, re-run the provisioning step, old-secret deliveries simply 401 until GitHub redelivers).
10. Optionally add a `github-funnel` entry to `lib/job_catalog.py` (mirroring `portfolio-dev-tunnel`'s shape) and a matching `lib/health_checks.py` check, so a dead Funnel shows up in Health like every other always-on service.
11. Run `dashboard/test/polling_guard.test.js` against the finished diff and confirm it passes with no `ALLOWLIST` edit.
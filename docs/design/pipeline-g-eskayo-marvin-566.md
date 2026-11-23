## North-star fit

**Reuses:** the request-handling shape of `dashboard/webhook-server/index.js`'s existing routes — `/merge-stage`'s pattern of `allowedPeerAddress(req.socket?.remoteAddress)` gating + a pure, independently-tested validator (`merge_stage_relay.js:cleanStageMessage`) — for the new peer-only `/gh-change` route; the peer fan-out-with-backoff engine in `merge_stage_relay.js:createStageRelay` (generalized to a path parameter, `createPeerRelay`) for forwarding to the laptop; `gh_auth.js:loadGhToken`'s "read a credential file once at startup, never throw" shape for the new webhook-secret loader; `safety_labels.js:handleSafetyRequest`'s "pure `{status, json}` handler, wired into `index.js` by a thin route" shape for the new GitHub-facing handler; and the **already-unconditional** `startChangeWatch(...)` call at the bottom of `index.js` (not primary-host-gated) as the "stays as backup" mechanism — it needs no new code, only to be left alone. `board_registry.py`'s `_gh(args)` subprocess-call shape is reused for the new idempotent hook-sync script.

**Simplest sufficient approach:** no new timer/interval anywhere — the webhook route is request-driven, the relay to the laptop is request-driven (fire-and-forget, same as the existing merge-stage relay), and the ETag watch that remains as backup is the one that already runs unconditionally today. Replay protection is a bounded in-memory window, not a service. GitHub hook registration is a one-time idempotent script, not a new always-on process.

**Resources:** spends a small amount of code (one new small module pair + a ~15-line generalization of an existing one) to remove the larger cost — the laptop's independent 20 s GitHub poll stops being the *only* way it learns about changes, cutting its share of the measured 16,111 gh calls/24 h once this is live (the actual slow-down of the interval is explicitly deferred by the ticket to a later, proven-reliable step, so this PR spends no extra calls either).

**Phone-OS direction:** a real push channel from GitHub is more OS-shaped than a timer (reachable, event-driven, works the same whether a dashboard window happens to be open).

**More capable, not more passive:** this is pure infrastructure — it removes latency and wasted polling without changing what the owner sees or does; no north star argues against it.

**Decisions:** none needed from the owner. The two forks the original ticket raised (Funnel vs. ngrok vs. relay; one endpoint vs. one per Mac) were already resolved by the owner on #1293 ("one Tailscale Funnel address on the Mac mini... passed on to the laptop, with the 20-second check kept as backup") and the rewritten ticket text matches that. Everything left (payload cap size, replay-window length, exact path name, secret file name) is an implementation detail, not a design fork.

---

## Design

**Mini-only, Funnel-exposed:** `POST /gh-webhook` on the existing webhook-server (`:7878`), reached publicly only through a Tailscale Funnel on the mini that forwards *just* that path. The route:
1. Reads the raw body with a size cap (413 over cap, before any parsing) — reuses `index.js`'s existing `readBody(req, limit)`.
2. Verifies `X-Hub-Signature-256` (HMAC-SHA256 over the raw bytes, timing-safe compare) against a secret loaded once at startup from `~/.claude/.gh-webhook-secret` (new `webhook_auth.js`, mirrors `gh_auth.js:loadGhToken`). No secret loaded, or no/wrong signature → refused, logged via `appendError` (reused, not reinvented).
3. Checks `X-GitHub-Delivery` against a bounded, time-windowed "seen" store to refuse exact replays.
4. Parses the (now-trusted) JSON, reads `repository.full_name`, and checks it against the same tracked-repo set `index.js` already computes (`readRegistry()` + `supportRepos()`) — untracked repo/event type: `200`, no-op, no error log (not an attack, just drift between GitHub's hook config and the current registry).
5. On acceptance: responds `200` immediately, then (fire-and-forget) calls the **same** reaction `index.js`'s ETag watcher already runs on change (extracted from its current inline `ping` callback into a named `reactToChange(repo)`), and relays `{repo}` to the laptop.

**Peer relay:** a new, tiny `github_change_relay.js` wraps a generalized version of `merge_stage_relay.js`'s peer-fan-out engine (extracted as `createPeerRelay({ peers, post, path, ... })`, with `createStageRelay` becoming a one-line wrapper around it so its existing behavior and tests are untouched) pointed at a new peer-only route `POST /gh-change`, gated by the *existing, unmodified* `allowedPeerAddress`. A sleeping/unreachable laptop never blocks the mini's response to GitHub and goes quiet-then-retries exactly like `/merge-stage` already does.

**Backup unchanged:** `startChangeWatch(...)` in `index.js` keeps running exactly as it does today, on both Macs, unconditionally — this already satisfies "the 20 s check still catches changes" whether the Funnel, the mini, or the relay is down, with zero new code. Slowing it down is explicitly out of scope per the ticket ("only once deliveries are proven reliable").

**GitHub-side subscriptions:** a new, idempotent `lib/webhook_setup.py sync` (reusing `board_registry.py`'s `_gh()` subprocess shape) reconciles each board + support repo's webhooks against the Funnel URL/events/secret — creates missing ones, fixes mismatched ones, leaves everything else alone, never prints the secret. Run once by hand after the Funnel is live; documented, not auto-triggered (keeping this PR's blast radius to app code + one manual step, not wiring into the hourly onboarding sweep).

**Docs:** `CONTEXT.md`'s "Triggers over polling" GitHub-state bullet amended to describe the webhook path, signature check, relay, and that the ETag probe is now explicitly the backup rather than the only channel. `webhook-server/README.md` gets the new contract + a short Funnel/secret-rotation ops note.

---

## Tests written first

`dashboard/test/github_webhook.js` (pure logic, no server):
1. Valid signature, tracked event, tracked repo → accepted, repo name returned.
2. Missing `X-Hub-Signature-256` → refused, nothing accepted.
3. Wrong/forged signature → refused (the ticket's explicit "forged or unsigned delivery is refused" AC).
4. Malformed signature header (not `sha256=<hex>`, wrong length) → refused without throwing (`timingSafeEqual` length mismatch handled).
5. No secret configured on this machine → every delivery refused, never throws (this is how the laptop's own instance behaves automatically, with no special-casing).
6. Oversized body → rejected before JSON parsing (huge-payload attack).
7. A replayed `X-GitHub-Delivery` id → ignored the second time, not re-accepted (replay attack).
8. Two concurrent deliveries with the same id → only one accepted (race safety; no `await` between check and record).
9. Event type outside `{push, pull_request, issues, check_run, check_suite}` → ignored, 200.
10. Valid signature, valid JSON, but `repository.full_name` not in the tracked set → ignored, 200, no error logged (repo-not-on-board misuse case).
11. Valid signature but unparseable/empty JSON body → refused safely, no throw (malformed input).
12. Wrong HTTP method/path reaching the handler → 404, same shape as other routes.

`dashboard/test/merge_stage_relay.test.js` (extend, existing cases untouched):
13. `createPeerRelay` with a custom path behaves identically to today's `createStageRelay` behavior (same quiet-backoff, same fire-and-forget guarantee) — proves the extraction changed nothing.

`dashboard/test/github_change_relay.js` (new):
14. The laptop asleep/unreachable when a delivery arrives: relay call returns immediately, never throws, peer goes quiet and is retried later (mirrors the proven merge-stage case for this exact scenario).
15. A peer list that throws, no peers, or a junk message: nothing sent, nothing thrown.
16. `/gh-change` only takes loopback/Tailscale callers — reuses the existing `allowedPeerAddress` fixtures; a LAN/internet address is refused.
17. End-to-end over a local HTTP server: a relayed `{repo}` reaches the peer's reaction path (mirrors `merge_stage_relay.test.js`'s existing "end to end over HTTP" test).

`lib/tests/test_webhook_setup.py` (new, mocked `gh`, never touches real GitHub):
18. Repo with no matching hook → plans a create.
19. Repo with a hook at the right URL but wrong events/secret → plans an update, leaves the hook id intact.
20. Repo with a hook already matching → plans nothing (idempotent re-run).
21. Repo with an unrelated hook (different URL, e.g. another integration) → left alone, never touched or deleted.
22. `gh` failing for one repo (rate-limited, no admin scope) → that repo reports an error, the others in the batch still complete.
23. The secret is never present in anything printed, logged, or returned by the sync report.

---

## Task List

1. `dashboard/webhook-server/webhook_auth.js`: add `loadWebhookSecret()` reading `~/.claude/.gh-webhook-secret` once, mirroring `gh_auth.js:loadGhToken` (never throws, returns `null` when absent).
2. `dashboard/webhook-server/github_webhook.js`: add `verifySignature`, the bounded replay-window store, `extractRepo`, and the orchestrating pure `handleGithubWebhook(...)` (tests 1–12 drive this).
3. `dashboard/webhook-server/merge_stage_relay.js`: extract `createPeerRelay({ peers, post, path, port, timeoutMs, quietMs, now, log })`; make `createStageRelay` a thin wrapper over it with `path: '/merge-stage'`. No other export changes (test 13).
4. `dashboard/webhook-server/github_change_relay.js`: add `createChangeRelay` (wraps `createPeerRelay` with `path: '/gh-change'`) and `cleanChangeMessage` (tests 14–17).
5. `dashboard/webhook-server/index.js`: extract the inline `ping` callback (lines ~539–553) into a named `reactToChange(repo)`; load the webhook secret and create the replay store and `changeRelay` at startup; wire `POST /gh-webhook` (GitHub-facing, uses `handleGithubWebhook`, calls `reactToChange` + `changeRelay` on acceptance) and `POST /gh-change` (peer-only, `allowedPeerAddress`-gated, calls `reactToChange`); pass `reactToChange` into the existing `startChangeWatch({ ping: reactToChange, ... })` call, unchanged otherwise.
6. `lib/webhook_setup.py`: add `existing_hooks`, `plan_hook_changes` (pure), `apply_hook_changes`, and a `sync` CLI entry point, reusing `board_registry.py`'s `_gh()` subprocess shape and reading repos from the registry + support-repo list (tests 18–23).
7. `CONTEXT.md`: amend the "Triggers over polling" GitHub-state bullet to describe the webhook path, HMAC check, peer relay, and the ETag probe's new role as backup; reference marvin#566.
8. `dashboard/webhook-server/README.md`: document the `POST /gh-webhook` and `POST /gh-change` contracts, the Funnel setup command, and the secret-rotation steps (generate, update via `lib/webhook_setup.py sync`, restart the service).
9. `dashboard/test/polling_guard.test.js`: run the guard after the above; add an allowlist entry **only if** the replay-window store trips the `ttl`-name heuristic despite being named to avoid it (e.g. `REPLAY_WINDOW_MS`), with a one-line reason distinguishing it from a staleness cache.
10. Manual verification (not unit-testable): bring up the Funnel on the mini, run `lib/webhook_setup.py sync`, make a real change on a board repo, confirm the dashboard updates within seconds on both Macs, then kill the Funnel and confirm the 20 s backup still catches the next change.
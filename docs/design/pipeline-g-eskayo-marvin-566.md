Good, enough context. Here's the plan.

## North-star fit

**Reuses:** the peer-forwarding pattern already proven in `merge_host_announce.js` (`announceMergeHost`/`relayMergeHostUp`: fire-and-forget POST to every registered peer over Tailscale, each timeout-bounded) and `merge_stage_relay.js`'s `allowedPeerAddress` (loopback/Tailscale-only IP guard, already gating `/merge-stage`); the secret-file-loading pattern in `gh_auth.js`'s `loadGhToken` (`~/.claude/.<name>`, mode 600, never logs the value, tolerates a missing file); the bounded-eviction `Map` from `merge_stage_relay.js`'s `createLiveMerges` (no timer needed for cache bounds); and the exact "repo changed" effect already in `webhook-server/index.js`'s `startChangeWatch` `ping` callback (`githubFeed?.refresh`, `rebuildCheck`, `refreshFacts().finally(() => mergeQueue.kick(repo))`, `forwardRefreshPing` to dashboard + mobile) — this ticket extracts that callback into a named `onRepoChanged(repo, source)` so the new webhook path and the existing poll both drive the same trigger, rather than duplicating it.

**Simplest sufficient approach:** no new state machine, no payload trust beyond "something changed" — a verified webhook just calls the same idempotent refresh the poller already calls, sooner. Replay/registry/body-size checks are the minimum needed to keep an internet-reachable endpoint safe; nothing else about `gh_watch.js` changes.

**Resources:** cuts the dominant cost of the 20 s poll (most GitHub calls become pure overhead once push works) while spending nothing new at idle — the webhook route is inert until GitHub calls it. The Funnel setup script and CONTEXT.md edit are one-time, not recurring cost.

**Capability:** the user is not involved in the loop at all here (machine-to-machine latency), so this is squarely a "more capable, not more passive" win — faster dashboard truth, lower rate-limit pressure, freeing the real API budget (#1238) for calls that need it.

**Where it runs:** the Mini only gets the public Funnel + webhook route (it's the registry's "desktop"/primary host, already the one `isPrimaryHost()` picks for the GitHub-feed writer); the laptop keeps running its own independent 20 s poll and now also a peer-only relay route reachable only over Tailscale.

**Correction to the ticket's stated fit:** none — the "one Funnel on the mini, signature-checked, relayed to the laptop, 20 s kept as backup" design matches what's actually buildable from the existing code: `peerHosts()`/`allowedPeerAddress` already exist for exactly this fan-out, and `startChangeWatch` is already unconditional on both Macs, so "the 20 s check stays" requires no code change — just leaving it alone.

**Important correctness point from reading the code (likely relevant to the 2 prior review failures):** a Tailscale Funnel request arrives at the Node process already proxied through `tailscaled` — `req.socket.remoteAddress` will look local/Tailscale-ish even though the real caller is GitHub on the public internet. So `/github-webhook` **cannot** be protected by `allowedPeerAddress`; it must be protected by HMAC signature alone. `allowedPeerAddress` is only valid on the new peer-to-peer relay route (`/github-relay`), which is never Funnel-exposed. I'll keep these two trust boundaries explicit and separately tested.

## Tests to write first

In `dashboard/test/`, mirroring `merge_host_announce.test.js` / `merge_stage_relay.test.js` style (pure functions, no live server needed except where exercising the HTTP wiring):

**From "How we'll try to break it":**
1. A replayed delivery (same `X-GitHub-Delivery` id, same signed body, sent twice) — second is rejected/ignored, not double-processed.
2. A payload over the size cap — rejected (413-equivalent) without buffering the whole thing into memory.
3. A delivery for a repo not in `readRegistry()`/`supportRepos()` — ignored, no `onRepoChanged` call, no relay to peers.
4. The peer (laptop) unreachable/asleep when a verified delivery arrives — the relay POST never throws, never delays the Mini's own `onRepoChanged` or its 200 response (mirrors `announceMergeHost`'s "a peer that is down never throws" test).

**Misuse the section didn't list, required by north-stars.md's "tests try to break it":**
5. Missing `X-Hub-Signature-256` header → rejected.
6. Signature present but wrong (tampered body or wrong secret) → rejected.
7. Signature header malformed (wrong length / non-hex) → rejected without the `crypto.timingSafeEqual` length-mismatch throwing.
8. Empty body / unparseable JSON → rejected cleanly (400-equivalent), not a crash.
9. Missing/unknown `X-GitHub-Event` → ignored safely.
10. An event type outside the forwarded five (e.g. `star`) → accepted-but-ignored (200, no action) — ticket's forward list is exact.
11. Two different valid deliveries (different ids) for the same repo arriving back-to-back → both trigger `onRepoChanged`, dedup is keyed by delivery id, not by repo.
12. Delivery-id cache is bounded (cap + eviction, `createLiveMerges`-style) so long uptime can't leak memory — no `setInterval` needed, so no new `polling_guard` entry.
13. Webhook secret file missing/unreadable at startup (a person's setup mistake) → server still starts; every delivery is safely rejected rather than the process throwing (mirrors `loadGhToken`'s tolerance).
14. `POST /github-relay` from an address that is neither loopback nor Tailscale → 403 via `allowedPeerAddress`, reused unchanged.
15. The existing `gh_watch.js` 20 s change-detector and check-watch keep running unmodified — assert `startChangeWatch`/`startCheckWatch` registration in `index.js` is untouched by the new routes (regression guard that the backstop really is still there "while the endpoint is down").

## Decisions

None — the owner's choice on the macro design is already recorded (#1293, `t566-endpoint`). The remaining points (route path names, secret file name/location, body-size cap, delivery-id dedup scope) are ordinary engineering details consistent with existing patterns (`gh_auth.js`, `merge_stage_relay.js`), not judgment calls for the owner. Actually registering the webhook (URL + secret) in each board repo's GitHub settings, and running the Funnel/serve setup on the Mini, are one-time operational steps outside this PR's code — the PR ships the route, the script, and the documented steps; activation happens once the PR is on the Mini, same as prior infra tickets (#762, #1223) shipped code separately from the operator flipping it on.

## Task List

1. `dashboard/webhook-server/github_webhook.js`: pure functions — `verifySignature(secret, rawBody, header)` (timing-safe, length-checked first), `parseDelivery(headers, rawBody)` → `{event, deliveryId, repo}` or `null` on anything malformed, `createDeliveryDedup({cap})` → `{seen(id)}` (bounded Map, oldest evicted), `loadWebhookSecret(env, home, read)` (file-based, mirrors `loadGhToken`), and `isForwardedEvent(event)` (the five-event allowlist).
2. `dashboard/webhook-server/github_relay.js`: `relayGithubChange({ peers, repo, event, post })` (fire-and-forget to each peer's `/github-relay`, timeout-bounded, `Promise.allSettled`, modeled on `announceMergeHost`) and `receiveGithubRelay(body)` → validated `{repo, event}` or `null`.
3. `dashboard/webhook-server/index.js`: extract the existing `startChangeWatch` `ping` callback body into `onRepoChanged(repo, source)`; wire `POST /github-webhook` (raw-body read with a size cap, signature + registry + dedup checks, calls `onRepoChanged` then `relayGithubChange`, responds 200 before the relay settles) and `POST /github-relay` (guarded by `allowedPeerAddress`, calls `onRepoChanged`).
4. Add a raw-`Buffer` body reader (`readRawBody(req, limit)`) alongside the existing string `readBody`, since HMAC needs the exact bytes GitHub signed.
5. Write the tests in step "Tests to write first" against `github_webhook.js`/`github_relay.js` (and the `index.js` wiring regression check) — red first, then make them pass.
6. `dashboard/webhook-server/scripts/setup_github_funnel.sh`: idempotent `tailscale serve`/`tailscale funnel` commands exposing only the webhook path, with the secret-file and rotation steps documented alongside it.
7. `dashboard/webhook-server/README.md`: add a `Contract: POST /github-webhook` section (request shape, response codes, secret file path, rotation steps) parallel to the existing `/approve`/`/deny` sections.
8. `CONTEXT.md` "Triggers over polling": amend with the new GitHub-push bullet (Funnel on the Mini, HMAC-verified, five event types, registry + replay checks, relayed to peers, 20 s check-detector and check-watch kept unmodified as the backstop).
9. `dashboard/test/polling_guard.test.js`: update the `gh_watch.js`/`index.js` `ALLOWLIST` reason text to note real push now exists (marvin#566) and these remain the backstop — no new timer, so no count change.
10. Run the full dashboard test suite (not just the new files) before calling this done, per the "full suites before a hand-merge" rule.
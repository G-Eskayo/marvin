Good, I have enough context now to write the plan.

## North-star fit

Reuses, before adding anything new:
- **`webhook-server/merge_host_announce.js`** (`announceMergeHost`/`relayMergeHostUp`) and **`merge_stage_relay.js`** (`allowedPeerAddress`, the per-host send queue) — the exact "Mini tells a peer's webhook-server something changed, over Tailscale, port 7878" shape already built for `/merge-host-up` and `/merge-stage`. Forwarding an accepted GitHub delivery to the laptop is the same shape again, not a new one.
- **`device_identity.js`** (`isPrimaryHost`, `peerHosts`) — already picks the Mini as the one GitHub-reading host (ADR 0032) and already lists the laptop's Tailscale name. No new device logic.
- **`webhook-server/index.js`'s inline `ping(repo)`** callback (what the 20s ETag watch does on a detected change: `githubFeed?.refresh`, `rebuildCheck`, `refreshFacts` + `mergeQueue.kick`, `forwardRefreshPing` to the local dashboard/mobile backend) — this becomes a named, exported function both the existing poller and the new webhook handler call, so a push and a poll-detected change do exactly the same thing downstream. `github_feed_writer.js`'s per-repo coalescing (`inflight` Map) already turns a burst of same-repo signals into at most one read running + one queued, so a burst of webhook deliveries for one repo can't multiply `gh` calls.
- **`webhook-server/safety_labels.js`'s `handleSafetyRequest({method,url,body}, run) -> {status, json}`** shape — a pure, dependency-injected handler tested without a real HTTP server (`safety_labels_webhook.test.js`). The new GitHub-webhook handler follows the same shape.
- **`index.js`'s `readBody(req, limit)`** (used for `/safety/label`, `/portfolio/*`) — the existing oversized-body cap (413), reused for the public endpoint instead of inventing a new limit.
- **`readRegistry()` (`boards.js`) + `supportRepos()` (`support_sync.js`)** — the same repo set the ETag watch already computes (`[...new Set([...readRegistry().map(b=>b.repo), ...supportRepos()])]`) becomes the one allow-list for "is this repo watched," reused rather than duplicated.
- **`gh_auth.js`'s `~/.claude/.gh-token`-file pattern** — the webhook secret is stored the same way (a 600-mode file under `~/.claude/`, read once at startup, never logged), not a new secrets mechanism.
- **`refusal_log.js`'s fail-soft `appendFileSync` JSONL pattern** — reused for a new `github-webhook-refusals.jsonl` instead of a new logging mechanism.

No existing pattern covers Tailscale Funnel exposure or HMAC verification — both are genuinely new (confirmed: no `createHmac`/`X-Hub-Signature` anywhere in the repo, and `webhook-server/README.md` says today's server has "no auth... before this is exposed beyond localhost").

Simplest sufficient approach: the public endpoint does exactly one new thing (verify HMAC, parse event, check the repo is watched, dedupe by delivery id) and then calls the same local pipeline polling already triggers, plus one forward to the laptop reusing the peer-fan-out shape. No new timers, no new polling-guard entry (the webhook path has none), no change to `gh_watch.js`'s interval — it stays as the backstop the ticket asks to keep.

Resources: this *replaces* up-to-20s-latency polling with push on the Mini, and *adds* one more trigger (the Mini forwarding to the laptop) in place of the laptop's own independent 20s poll noticing the same change later — net GitHub calls per change event are roughly unchanged (same `githubFeed.refresh`/list calls fire once per repo per change either way, coalesced already), but call *latency* and the dashboard's staleness window drop from ~20s to seconds, which is what the ticket purposely measures (not call-volume, which is #1238's separate ticket). Runs on the Mac mini (the registry's one "desktop"-kind machine, ADR 0032, already the sole GitHub-feed writer) because that's the one place a public Funnel address and the shared secret are allowed to live; the laptop stays a pure receiver, no Funnel of its own.

Leaves the user more capable: Gil stops being the thing that notices a change is late (no behavior change for him at all — the dashboard just gets faster and the system gets one less polling dependency to reason about).

## Decisions

<!-- marvin:decisions -->
### t566-webhook-registration: How does each board/support repo's GitHub webhook actually get configured to point at the Funnel URL?
- [ ] A script (`gh api repos/{repo}/hooks`) run from the same 20s tick that already recomputes the watched-repo set, so a repo added to or removed from the board gets its webhook created/deleted automatically — needs the stored `GH_TOKEN` to carry webhook-admin scope, which it may not today (recommended)
- [ ] Documented as a one-time manual step per repo (exact payload URL, content type, secret, events to tick) in `webhook-server/README.md`; MARVIN never touches repo-level webhook config
- [ ] Automated, but gated behind a confirmation each time a new repo would get a webhook added (no silent scope expansion)

### t566-secret-rotation: What does "rotation documented" mean operationally — is a short gap during rotation acceptable?
- [ ] Simple cutover: generate a new secret, update the Mini's local file and each repo's webhook config, done — the kept 20s ETag backstop already covers the few-minute gap while deliveries briefly fail signature checks (recommended)
- [ ] Dual-secret grace window: the verifier accepts either the current or the immediately-previous secret for a configurable overlap period, so rotation never produces a single refused delivery

## Tests to write first

One file per new module, `safety_labels_webhook.test.js`-style (pure handler, fake deps, no real HTTP server):

**`dashboard/test/github_webhook.test.js`** (new module `webhook-server/github_webhook.js`):
1. Valid HMAC-SHA256 signature (`X-Hub-Signature-256`) on a watched repo's `push`/`pull_request`/`issues`/`check_run`/`check_suite` event → 200, and the injected `onChange(repo)` is called exactly once.
2. **Forged signature** (wrong secret / tampered body) → refused (401/403), `onChange` never called, a line appended to the refusal log — the ticket's acceptance criterion.
3. **Missing `X-Hub-Signature-256` header entirely** → refused, same as forged (not silently accepted as "unsigned means trusted").
4. **Secret file missing/unreadable at startup** → every delivery is refused (fail closed), never falls back to "no verification."
5. **Huge payload** (over the body cap) → 413, body never fully buffered/parsed, `onChange` never called — same cap shape as `/safety/label`/`/portfolio/*`.
6. **Delivery for a repo not on the board and not a support repo** → 200 (so GitHub doesn't retry forever), `onChange` never called, no forward to peers.
7. **Replayed delivery** — same `X-GitHub-Delivery` id sent twice (valid signature both times) → the second is a no-op (not reprocessed, not forwarded again), still answers 200.
8. **Malformed/non-JSON body**, **empty body**, **top-level array/string instead of object**, and a body carrying `__proto__`/extra fields → refused cleanly (400), never throws, never leaks the extra fields onward.
9. **Wrong HTTP method or path** → 404, exactly like `handleSafetyRequest`'s existing fallthrough test.
10. **Concurrent deliveries for the same repo** (two valid, distinct-delivery-id events arrive before the first's downstream work finishes) → collapse to the existing coalescing (`githubFeed` `inflight` behavior is exercised, not duplicated); concurrent deliveries for *different* repos both go through independently.
11. **The downstream `onChange` throws or its awaited work rejects** (e.g. `gh` fails) → the webhook still answers GitHub 200 promptly (response is not blocked on the local refresh), matching `/mr-ready`'s "responds before the forward resolves" pattern.

**`dashboard/test/github_webhook_relay.test.js`** (new module reusing `merge_host_announce.js`'s shape, e.g. `relayGithubChange`/`createChangeAnnouncer`):
12. Mini receiving an accepted delivery posts to each peer's `/github-change` endpoint (one POST per entry in `peerHosts()`), with a minimal body (repo, nothing secret).
13. **The laptop is asleep/unreachable** when the forward is attempted → the post fails silently (caught, logged), the Mini's own response to GitHub is unaffected, and nothing retries/queues (the kept 20s backstop is what catches the laptop up, per the ticket).
14. The laptop's own `/github-change` receiver only accepts the Mini's Tailscale/loopback address (`allowedPeerAddress`, reused) — a request from any other address is refused, matching `/merge-stage`'s existing guard.
15. The laptop's receiver, on a valid forwarded repo, calls its *local* `onChange(repo)` directly — it does **not** re-fetch/re-verify against GitHub (the Mini already did that); and an invalid/unrecognized repo name in the forwarded body is a no-op, not a crash.
16. A malformed or oversized forwarded body is refused (reuses `cleanStageMessage`-style validation, capped size).

**Existing-behavior regression** (no new test file; extend `gh_watch.test.js` or `polling_guard.test.js` assertions):
17. `startChangeWatch`'s 20s interval is still started unconditionally at the same `intervalMs = 20_000`, not gated by webhook health — "while the endpoint is down" and "on open, after a missed delivery" still work with zero code changes to `gh_watch.js` itself.
18. `polling_guard.test.js`'s allowlist entries for `webhook-server/gh_watch.js` and `webhook-server/index.js` still pass with updated reason text (no new entry needed — the webhook path adds no timer).

Misuse categories from the ticket's own list are covered above (replay #7, huge payload #5, repo not on board #6, laptop asleep #13). Additional misuse not called out by name in the ticket but required by the project's adversarial-testing rule: bad/empty/malformed input (#8), each dependency failing — secret file (#4), downstream `gh`/local refresh (#11), peer unreachable (#13) — repeats/concurrency (#7, #10), wrong permissions in the fail-closed sense (#4), and a person's mistake re-sending a stale/forged delivery while testing (#2, #3, #7).

## Task List

1. Extract the inline `ping(repo)` callback at the bottom of `dashboard/webhook-server/index.js` into a named, exported `onRepoChanged(repo)` (or similarly named) function with the same body (githubFeed refresh, rebuildCheck, refreshFacts+mergeQueue.kick, forward to local dashboard/mobile refresh ports); wire the existing `startChangeWatch`'s `ping` to call it, unchanged behavior.
2. Extract the watched-repo-set expression (`[...new Set([...readRegistry().map(b=>b.repo), ...supportRepos()])]`) into a small shared helper so both the ETag watch and the new webhook handler use the same allow-list.
3. Write `webhook-server/github_webhook_secret.js`: load the webhook secret from a new `~/.claude/.github-webhook-secret` file (mirrors `gh_auth.js`), 600 mode, missing/unreadable → `null` (never throws), plus an HMAC-SHA256 verify function using `crypto.timingSafeEqual`.
4. Write `webhook-server/github_webhook.js`: `handleGithubWebhookRequest({method, url, headers, body}, deps)` — verifies signature (fail closed if no secret loaded), enforces the body-size cap, parses the event, checks the repo against the watched-repo helper, dedupes by `X-GitHub-Delivery` (bounded in-memory set, same no-disk-state style as `createChangeDetector`'s `seen` map), and on acceptance calls injected `onChange(repo)` and `forwardToPeers(repo)` without awaiting either before responding. Appends refused/forged attempts to a new `github-webhook-refusals.jsonl` via the `refusal_log.js`-style fail-soft append.
5. Write `webhook-server/github_webhook_relay.js`: the Mini-to-peer forward (reusing `allowedPeerAddress` and the `announceMergeHost`-style fan-out) — `relayGithubChange({repo, peers, post})` posting to each peer's new `/github-change` path, and a receiver-side `handleGithubChangeRequest` that checks `allowedPeerAddress`, validates the body, and calls local `onRepoChanged(repo)`.
6. Wire both into `dashboard/webhook-server/index.js`: route the new public path (e.g. `/github-webhook`) through `handleGithubWebhookRequest`, and `/github-change` through the relay receiver; pass `onChange: onRepoChanged` and `forwardToPeers: (repo) => relayGithubChange({repo, peers: peerHosts(), post: ...})`.
7. Resolve `t566-webhook-registration` and `t566-secret-rotation` with Gil; implement whichever registration option is chosen (script or documented manual step) and write the rotation procedure into `webhook-server/README.md`.
8. Set up the Tailscale Funnel on the Mini (`tailscale serve`/`tailscale funnel`) mapping only the `/github-webhook` path to local port 7878, documented step-by-step in `webhook-server/README.md`; generate and store the secret file.
9. Update `dashboard/test/polling_guard.js`'s `ALLOWLIST` reason text for `webhook-server/gh_watch.js` and `webhook-server/index.js` to describe the 20s ETag watch as the backstop behind the GitHub webhook push (#566), per the ticket's required allowlist update — no new entries, no interval change.
10. Amend `CONTEXT.md`'s "Triggers over polling" section: record the Funnel/webhook design (events covered, signature check, fail-closed on missing secret, the kept ETag backstop and when it's expected to slow down), replacing the "Real GitHub webhooks were rejected" line with the new decision, and link marvin#566.
11. Write and land all tests listed above before/alongside each module (red-green-refactor), run the full `vitest run` suite in `dashboard/`, and confirm the polling-guard test still passes with zero new allowlist entries.
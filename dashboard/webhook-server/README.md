# MR-approval webhook contract

`G-Eskayo/marvin#11`'s dashboard-side "Approve" button POSTs here.
`G-Eskayo/marvin#11` is explicit that the exact n8n node topology is
separate downstream design/build work — this directory is a real, working
reference implementation of the contract that topology needs to satisfy,
not a stub. Swap it for an actual n8n workflow (Webhook node → Execute
Command node, same request/response shape) whenever that gets built; the
dashboard doesn't need to change either way, since it only knows the URL
in `MARVIN_MR_WEBHOOK_URL` (and, for Deny, `MARVIN_MR_DENY_WEBHOOK_URL`).

## Contract: `POST /approve`

**Request**: JSON body `{ "pr_url": "<full GitHub PR URL>" }`

**Behavior**: runs `gh pr merge <pr_url> --merge` and waits for it to finish.

**Response**:
- `200 { "merged": true }` on success
- `500 { "merged": false, "error": "<message>" }` on failure (bad URL, merge conflict, already merged, etc.)

**Streamed progress (marvin#568)**: send `Accept: application/x-ndjson` and the answer is `200` with one JSON line per
stage event as it happens, `{"type":"progress","event":{id, seq, stage, state, at, detail?, count?, machine?, estimateMs?}}`
(stages: queued, fetching, rebasing, installing, tests, merging, after, done; states: running, done, failed, skipped),
then one `{"type":"result","status":<the status above>,"body":<the body above>}`. A stream that ends with no result
line means the webhook went away mid-merge: the dashboard shows "interrupted". Without the header the response is
exactly as above. The same events are also posted to the dashboard's refresh port on this Mac as
`{"topics":["merge"],"merge":{"url","event"}}`. Each merge's start, stage changes and finish are logged to
`~/.claude/logs/dashboard-webhook.log`; merges in flight are kept in `~/.claude/logs/merge-inflight.json` and reported
as interrupted when the webhook starts again; real durations go to `~/.claude/logs/gate-run-durations.jsonl`.

## Contract: `POST /deny`

ADR 0025's Deny action — one endpoint, two terminal actions carried in `action`.

**Request**: JSON body
```
{
  "action": "send_feedback" | "drop",
  "pr_url": "<full GitHub PR URL>",
  "ticket_number": <originating ticket's issue number, or null>,
  "reasons": ["<reason category>", ...],
  "comment": "<optional free text>"
}
```

**Behavior**:
- `send_feedback`: posts the structured feedback (reasons + comment) as a comment on both the PR
  and its ticket, releases the ticket's `claimed:*` label(s), and adds `needs-reengagement` (created
  on first use) so a future review/debug/improve pipeline can find it. Leaves the PR and ticket open
  — ADR 0025 explicitly defers how that pipeline consumes the tag.
- `drop`: closes the PR and its ticket and releases the claim. No comment, no re-engagement — this
  is the irreversible path (see ADR 0025's "Known gap").

**Response**:
- `200 { "done": true }` on success
- `400 { "done": false, "error": "<message>" }` on a malformed request (bad JSON, unknown `action`)
- `500 { "done": false, "error": "<message>" }` on failure (bad URL, `gh` call failed, etc.)

## Running it

```
node webhook-server/index.js          # listens on :7878 by default
PORT=8080 node webhook-server/index.js
```

The dashboard defaults to `http://localhost:7878/approve` and
`http://localhost:7878/deny`; override with `MARVIN_MR_WEBHOOK_URL` /
`MARVIN_MR_DENY_WEBHOOK_URL` if this runs on a different port or machine.

## Contract: `POST /gh-webhook` (marvin#566)

GitHub's webhook delivery — receives signed notifications of changes to board repos.
Called by GitHub (the Funnel must be reachable from the network, behind a tunnel or on a stable IP).

**Request**: JSON body (GitHub's full webhook payload for push, pull_request, issues events)
with signature and delivery headers:
- `x-hub-signature-256: sha256=<hmac>` (HMAC-SHA256 of the body, signed with the webhook secret)
- `x-github-delivery: <UUID>` (unique delivery ID, used for replay-window deduplication)
- `content-type: application/json`

**Behavior**: 
1. Verifies the HMAC signature against the secret in `~/.claude/.gh-webhook-secret`
2. Checks the replay window: rejects duplicate deliveries (same UUID within 5 min)
3. Extracts the repo from the payload (`repository.full_name`)
4. Calls the same `reactToChange(repo)` as the ETag-backed change-detector would
5. Relays to other Macs via `POST /gh-change` (peer-only, loopback/Tailscale)

**Response**:
- `202 { "ok": true }` on success (accepted for async processing)
- `202 { "ok": false, "error": "duplicate delivery" }` on replay-window hit
- `400 { "ok": false, "error": "<message>" }` on signature failure, invalid payload, etc.

**Verification logic** (not exposed, internal):
- Secret is loaded from `~/.claude/.gh-webhook-secret` at startup (`webhook_auth.js:loadWebhookSecret`)
- Signature is verified with `crypto.timingSafeEqual` to prevent timing attacks
- Payload is parsed as JSON; repo is extracted only if `repository.full_name` exists

**Limitations**:
- Webhook secret is managed manually or via `lib/webhook_setup.py sync`; rotation requires restarting the webhook server
- Only board repos and support repos (defined in the registry) trigger changes

## Contract: `POST /gh-change` (marvin#566)

Peer-to-peer change relay: other Macs' webhooks forward their changes here (private network only).
Only the owner's Macs may send it (loopback or Tailscale ranges, checked with `allowedPeerAddress`).
Never relayed onward (peer-only, never federated).

**Request**: JSON body `{ "repo": "<owner/repo>", "event": <optional event data> }`

**Behavior**: calls `reactToChange(repo)` to trigger the same response as a local change detection.

**Response**:
- `200 { "ok": true }` on success
- `403 { "ok": false }` if the sender is not on a private network (loopback or Tailscale)
- `400 { "ok": false }` on invalid JSON or missing repo

## Setup: GitHub webhook registration

**Once, at setup time**: generate a secret and store it, then register webhooks on all board repos.

```bash
# Generate a secret and store it
openssl rand -hex 32 | tee ~/.claude/.gh-webhook-secret

# Start the webhook server and run the setup
PORT=7878 node dashboard/webhook-server/index.js &
MARVIN_WEBHOOK_URL='https://your-funnel-domain.com/gh-webhook' python3 lib/webhook_setup.py sync

# Check that webhooks are registered
MARVIN_WEBHOOK_URL='...' python3 lib/webhook_setup.py existing
```

**Secret rotation** (if compromised):
1. Generate a new secret: `openssl rand -hex 32 > ~/.claude/.gh-webhook-secret`
2. Restart the webhook server
3. Manually delete the old webhook(s) from GitHub (they'll keep sending with the old secret and be rejected)

(Future work: add a `rotate` command to `lib/webhook_setup.py` to automate step 3.)

## Deliberately out of scope here

No auth on peer relay (`/gh-change`), no queueing, no retry. This is the same "dashboard is a trigger,
not a queue" scope line #11 itself draws. The GitHub webhook is HMAC-verified but only as protection
against accidental misuse (bad config, malicious caller on the network); if the secret is stolen,
GitHub itself validates the sender (a thief would need to also compromise GitHub). A real production
setup should add TLS and optional bearer-token auth to `POST /gh-change` before it's exposed beyond
the owner's private network.

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

## Contract: `POST /github-webhook`

**marvin#566**: GitHub push notifications, Tailscale Funnel exposed, HMAC-verified, replay-deduplicated.

**Request**: JSON body with GitHub webhook payload (any of: `pull_request`, `pull_request_review`, `issues`, `issue_comment`, `push`).
- Header: `X-Hub-Signature-256: sha256=<hmac-sha256(secret, raw-body)>`
- Header: `X-GitHub-Delivery: <UUID>`
- Header: `X-GitHub-Event: <event-type>`

**Secret**: stored in `~/.claude/.webhook-secret` (see setup below).

**Response**:
- `200 { "ok": true }` on success (processed or duplicate)
- `200 { "ok": true, "duplicate": true }` on replay (same delivery ID seen recently)
- `400 / 401 / 413` on error (bad JSON, invalid signature, body too large)

**Setup**:

```bash
# Generate the secret and expose via Tailscale Funnel (one time, idempotent):
bash webhook-server/scripts/setup_github_funnel.sh

# Register in GitHub (GitHub App / Webhook):
# 1. Set Payload URL to: https://<your-tailscale-domain>.ts.net/github-webhook
# 2. Set Secret to: (output from setup script above, stored in ~/.claude/.webhook-secret)
# 3. Select events: pull_request, pull_request_review, issues, issue_comment, push
# 4. Delivery method: application/json
# 5. Active: on

# To rotate the secret:
openssl rand -hex 32 > ~/.claude/.webhook-secret
# Update the secret in GitHub, restart the webhook server.
```

**Funnel configuration**: The setup script uses `tailscale serve --set-path=/github-webhook` to expose 
only the webhook endpoint (not the entire server), and `tailscale funnel on 443` to make it public. 
This prevents `/github-relay` or other paths from being exposed unintentionally. The relay endpoint 
(`/github-relay`) remains protected by loopback/Tailscale `allowedPeerAddress` checks.

**Behavior**: parses the delivery, verifies signature (timing-safe), checks replay dedup, then:
1. Calls the same repo-change handler as polling (refreshFacts, mergeQueue.kick, etc.)
2. Relays to peers so their dashboards see the change immediately (they have ~20s polling backstop)
3. Responds 200 before relay settles (fire-and-forget)

Allowed event types are the five in the allowlist (line 571); others are accepted (200) but ignored.

## Running it

```
node webhook-server/index.js          # listens on :7878 by default
PORT=8080 node webhook-server/index.js
```

The dashboard defaults to `http://localhost:7878/approve` and
`http://localhost:7878/deny`; override with `MARVIN_MR_WEBHOOK_URL` /
`MARVIN_MR_DENY_WEBHOOK_URL` if this runs on a different port or machine.

## Deliberately out of scope here

No auth on `/approve` or `/deny`, no queueing, no retry. This is the same "dashboard is a trigger,
not a queue" scope line #11 itself draws — a real production n8n workflow
should add whatever's appropriate (auth on the webhook, at minimum) before
this is exposed beyond localhost. The `/github-webhook` endpoint is signature-verified
and should be safe to expose via Tailscale Funnel to your GitHub instance.

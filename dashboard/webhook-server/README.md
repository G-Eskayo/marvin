# MR-approval webhook contract

`G-Eskayo/marvin#11`'s dashboard-side "Approve & Merge" button POSTs here.
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

## Deliberately out of scope here

No auth, no queueing, no retry. This is the same "dashboard is a trigger,
not a queue" scope line #11 itself draws — a real production n8n workflow
should add whatever's appropriate (auth on the webhook, at minimum) before
this is exposed beyond localhost.

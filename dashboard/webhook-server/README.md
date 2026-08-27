# MR-approval webhook contract

`G-Eskayo/marvin#11`'s dashboard-side "Approve & Merge" button POSTs here.
`G-Eskayo/marvin#11` is explicit that the exact n8n node topology is
separate downstream design/build work — this directory is a real, working
reference implementation of the contract that topology needs to satisfy,
not a stub. Swap it for an actual n8n workflow (Webhook node → Execute
Command node, same request/response shape) whenever that gets built; the
dashboard doesn't need to change either way, since it only knows the URL
in `MARVIN_MR_WEBHOOK_URL`.

## Contract

**Request**: `POST /approve`, JSON body `{ "pr_url": "<full GitHub PR URL>" }`

**Behavior**: runs `gh pr merge <pr_url> --merge` and waits for it to finish.

**Response**:
- `200 { "merged": true }` on success
- `500 { "merged": false, "error": "<message>" }` on failure (bad URL, merge conflict, already merged, etc.)

## Running it

```
node webhook-server/index.js          # listens on :7878 by default
PORT=8080 node webhook-server/index.js
```

The dashboard defaults to `http://localhost:7878/approve`; override with
`MARVIN_MR_WEBHOOK_URL` if this runs on a different port or machine.

## Deliberately out of scope here

No auth, no queueing, no retry. This is the same "dashboard is a trigger,
not a queue" scope line #11 itself draws — a real production n8n workflow
should add whatever's appropriate (auth on the webhook, at minimum) before
this is exposed beyond localhost.

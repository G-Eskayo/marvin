# Mobile backend service

Standalone Node service that vets Tailscale device identity via allowlist and exposes a `/status` endpoint for mobile clients. Runs under launchd supervision: restarts on crash, listens only on this machine's Tailscale IPv4 address.

## Device gate

The service resolves the caller's Tailscale peer identity (via `tailscale whois --json <ip>`) and checks it against `~/.claude/mobile-allowlist.json`. Default deny: any lookup failure or missing peer name blocks the request.

## Allowlist

User-managed configuration at `~/.claude/mobile-allowlist.json`:

```json
{
  "devices": ["gils-iphone", "gils-ipad"]
}
```

Device names are case-insensitive Tailscale node names (first label of hostname). The allowlist is read on each request; no service restart needed to apply changes.

## Contract: Read-only Dashboard API

All routes return JSON responses with `{ "ok": <boolean>, "data": <data> | "error": <message> }` format.

### `GET /status`

**Response**:
- `200 { "ok": true, "status": "up", "uptimeSeconds": <n>, "version": "1.0.0" }` — allowlisted peer
- `403 { "ok": false, "error": "not allowlisted" }` — peer not in allowlist

### `GET /activity`

Lists ticket activity across projects.

**Response**: `200 { "ok": true, "data": [{ number, repo, key, currentStage, currentStatus, costUsd, failed, title, eventCount, lastEventAt, isLiveNow }, ...] }`

### `GET /health`

System health status.

**Response**: `200 { "ok": true, "data": { generated_at, overall, coverage, anomaly, checks } }`

### `GET /boards`

Board registry with project status.

**Response**: `200 { "ok": true, "data": [{ repo, label, color, due, dueHard, status }, ...] }`

### `GET /boards/ticket?repo=<repo>&number=<number>`

Fetch a single ticket.

**Query parameters**: `repo` (required), `number` (required)

**Response**: `200 { "ok": true, "data": { number, title, body, labels, url, state, comments } }`

### `GET /docs/repos`

List available documentation repos.

**Response**: `200 { "ok": true, "data": { generated_at, repos: [{ id, name, kind, status, local, ... }, ...] } }`

### `GET /docs/tree?id=<id>`

Get file tree for a documentation repo.

**Query parameters**: `id` (required, project ID or `__master__` for master doc)

**Response**: `200 { "ok": true, "data": { source, dir, tree: [{ path, label }, ...] } }`

### `GET /docs/content?id=<id>&path=<path>`

Get file content from a documentation repo.

**Query parameters**: `id` (required), `path` (required, URL-encoded file path)

**Response**: `200 { "ok": true, "data": <file content as string> }`

## Running it

```bash
# Install launchd service
bash ~/.agents/dashboard/mobile-backend/install.sh

# Start/stop via launchctl
launchctl start com.marvin.mobile-backend
launchctl stop com.marvin.mobile-backend

# Check status
launchctl print "gui/$(id -u)/com.marvin.mobile-backend"
tail -f ~/.claude/logs/mobile-backend.log
```

The service defaults to port 7880; override with `PORT` env var if needed (edit the plist).

### `GET /thread?limit=<n>&before=<id>`

Fetch thread history with optional pagination.

**Query parameters**: `limit` (optional, default 50), `before` (optional, cursor ID for pagination)

**Response**: `200 { "ok": true, "data": [{ id, source, role, text, sessionId, ts }, ...] }` (messages in reverse chronological order, newest first)

## Permission bridge: side-effecting actions

When the mobile client sends a message that triggers a side-effecting tool call (Bash, Edit, Write, etc.), the `permission_hook.js` subprocess intercepts the tool use, creates a pending action, and blocks until the action is approved or denied via these endpoints.

### `GET /pending-actions`

List all pending actions (pending, approved, or denied).

**Response**: `200 { "ok": true, "data": [{ id, toolName, toolInput, summary, sessionId, status, decision, reason, createdAt, resolvedAt }, ...] }`

### `POST /pending-actions/resolve`

Approve or deny a pending action.

**Request body**: `{ "id": "<action-id>", "decision": "allow"|"deny", "reason": "<optional-reason>" }`

**Response**: `200 { "ok": true, "data": { id, ... } }` on success, `400 { "ok": false, "error": "<message>" }` if action is not pending or invalid input

## Write actions: ticket reply and PR approve/deny

Mobile clients can perform side-effecting actions (ticket replies, PR approvals/denials) after confirming via device Face ID. All three routes require a `confirmed: true` field; requests without it are rejected with `403 { "ok": false, "error": "Action requires confirmation" }`.

### `POST /boards/ticket/reply`

Leave an owner's comment on a ticket and, if the ticket was waiting on it, requeue it automatically.

**Request body**: `{ "repo": "G-Eskayo/repo", "number": <ticket-number>, "body": "<comment-text>", "confirmed": true }`

**Response**:
- `200 { "ok": true, "data": { "posted": true, "requeued": <boolean>, "effect": "<description>", "warning": "<optional-message>" } }` on success
- `400 { "ok": false, "error": "<message>" }` on validation error (bad repo/number format, empty body, etc.)

The `effect` field describes what label changes were applied or attempted. The optional `warning` field appears when the comment posted successfully but the label change failed (the answer is still on the ticket, but requires manual requeue).

### `POST /mr/approve`

Approve a pull request for merging via the webhook contract.

**Request body**: `{ "prUrl": "<full-github-pr-url>", "confirmed": true }`

**Response**:
- `200 { "ok": true, "data": { "merged": <boolean>, "reengaged": <boolean>, "reason": "<optional-reason>" } }` on success
- `400 { "ok": false, "error": "<structured-error-message>" }` if the webhook returned a structured failure code (e.g., auth, merge conflict)
- `502 { "ok": false, "error": "<message>" }` if the webhook server is unreachable

The response body from the webhook is passed through unchanged. A `200` can mean either a merge (with `merged: true`) or a re-engagement route (with `reengaged: true`) — callers must check both fields.

### `POST /mr/deny`

Deny a pull request for rework or closure via the webhook contract.

**Request body**: `{ "prUrl": "<full-github-pr-url>", "ticketNumber": <number>, "action": "send_feedback"|"drop", "reasons": ["<reason1>", ...], "comment": "<feedback-text>", "confirmed": true }`

**Response**:
- `200 { "ok": true, "data": { "done": true } }` on success
- `400 { "ok": false, "error": "<message>" }` if `action` is invalid (must be "send_feedback" or "drop")
- `502 { "ok": false, "error": "<message>" }` if the webhook server is unreachable

`send_feedback` posts the comment to the PR, tags the ticket for the rework pipeline, and releases the current merge claim; `drop` closes the PR and ticket.

## Deliberately out of scope

Face ID authentication itself (handled by the mobile client), search endpoints. This backend provides read-only access to dashboard data, managed session state with side-effecting permission gating, and permission-gated write actions (ticket reply, PR approve/deny).

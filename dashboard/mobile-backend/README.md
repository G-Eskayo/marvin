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

## Mobile write actions (Face ID gated)

When the mobile client receives Face ID authentication on the device, three dashboard write endpoints become available.

### `POST /boards/input`

Post an owner comment on a ticket and optionally move it back to ready.

**Request body**: `{ "repo": "<owner>/<repo>", "number": <ticket-number>, "body": "<comment-text>", "confirmed": true }`

Requires `confirmed: true` (Face ID verified on client); missing or false returns `403`.

**Response**: `200 { "ok": true, "data": { posted, requeued, effect, warning? } }`

- `posted: true` — comment was successfully posted to the ticket
- `requeued: true` — ticket was also moved back to "ready" state (label changes succeeded); `false` if the label change failed (comment still posted)
- `effect: "awaiting_input" | "awaiting_feedback" | null` — which backlog the ticket was in
- `warning?: string` — if present, label change failed; user should try again or move the ticket by hand

Errors: `400` if fields are missing/invalid, or `postTicketInput` fails (repo validation, empty comment, etc).

### `POST /mr/approve`

Approve a pull request for merge.

**Request body**: `{ "url": "<pr-url>", "number": <pr-number>, "confirmed": true }`

Requires `confirmed: true`; missing or false returns `403`.

**Response**: `200 { "ok": true, "data": { ...result, cancelled: false } }`

The response body from the merge webhook, plus `cancelled: false` to distinguish from merge-time re-engagement.

Errors: `400` if fields are missing, `confirmed` is missing/false, or the PR fails the merge guard (wrong order, wrong base, sent back for rework, CI pending); `403` if the project profile has not opted in to merging from the dashboard. The error body includes `code` (e.g., `OUT_OF_ORDER`, `NO_MERGE_PROFILE`) and structured details from the webhook if available.

### `POST /mr/deny`

Deny a pull request (send feedback or close).

**Request body**: `{ "url": "<pr-url>", "number": <pr-number>, "ticketNumber": <ticket-number>, "action": "send_feedback"|"drop", "reasons": [<reason-codes>], "comment": "<optional-comment>", "confirmed": true }`

Requires `confirmed: true`; missing or false returns `403`.

**Response**: `200 { "ok": true, "data": { done: true } }`

Errors: `400` if fields are missing/invalid, or the repo is not set up for merging; `500` if the webhook call fails.

## Deliberately out of scope

Face ID authentication client-side behavior — the mobile app handles biometric verification and only sends `confirmed: true` after it succeeds. Search endpoints (#157). This backend provides read-only access to dashboard data, managed session state with side-effecting permission gating, and Face ID-gated write actions for dashboard initiation of ticket answers and PR review workflows.

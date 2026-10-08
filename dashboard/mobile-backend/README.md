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

### `GET /live`

Streams real-time updates as activity or agent changes occur.

**Response**: `200 application/x-ndjson` (chunked, streaming)
- Each line is a JSON object: `{ "topic": "activity" | "agents", "source": <string> }`
- Connection stays open until the client closes it
- Updates stream immediately as triggers fire or refresh pings arrive from the webhook

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

The internal refresh listener (receives pings from the webhook-server when changes occur) defaults to port 7881; override with `MARVIN_MOBILE_REFRESH_PORT` env var if needed.

### `GET /thread?limit=<n>&before=<id>`

Fetch thread history with optional pagination.

**Query parameters**: `limit` (optional, default 50), `before` (optional, cursor ID for pagination)

**Response**: `200 { "ok": true, "data": [{ id, source, role, text, sessionId, ts }, ...] }` (messages in reverse chronological order, newest first)

### `POST /offline-batch`

Batch-upload offline exchanges. Idempotent deduplication by client-assigned message ID; new exchanges get a Session-based review for memory curation.

**Request body**: `{ "exchanges": [{ clientId: "<unique-id>", role: "user"|"assistant", text: "<message>", ts?: <unix-ms> }, ...] }`

- `clientId` (required, string): Unique identifier per offline exchange — used for deduplication. Retry safety: re-sending the same batch is a no-op.
- `role` (required, "user" or "assistant"): Message role.
- `text` (required, string): Message content.
- `ts` (optional, unix milliseconds): Override timestamp. If omitted, current time is used.

**Response**:
- `200 { "ok": true, "data": { added: [<message-ids>], skipped: [<clientIds>], reviewed: <boolean> } }` — success
  - `added`: IDs of newly-appended messages.
  - `skipped`: Client IDs of exchanges that were already in the store (dedup).
  - `reviewed`: Whether a Session review was run (only true if new messages were added).
- `400 { "ok": false, "error": "<message>" }` — validation failed (empty array, missing required fields, invalid role, etc.)

**Semantics**:
- All messages are marked with `source: "offline"`.
- If the batch introduces any new exchanges, they are submitted to a Session for review, which decides what insights are worth saving to memory. The review is framed as offline backlog curation, not a live turn.
- All new messages in the batch are backfilled with the review's `sessionId` for continuity.
- Rotation policy (session length threshold) is applied after the review, same as chat turns.
- Pending summary is NOT consumed by the offline endpoint (only by chat turns).

## Permission bridge: side-effecting actions

When the mobile client sends a message that triggers a side-effecting tool call (Bash, Edit, Write, etc.), the `permission_hook.js` subprocess intercepts the tool use, creates a pending action, and blocks until the action is approved or denied via these endpoints.

### `GET /pending-actions`

List all pending actions (pending, approved, or denied).

**Response**: `200 { "ok": true, "data": [{ id, toolName, toolInput, summary, sessionId, status, decision, reason, createdAt, resolvedAt }, ...] }`

### `POST /pending-actions/resolve`

Approve or deny a pending action.

**Request body**: `{ "id": "<action-id>", "decision": "allow"|"deny", "reason": "<optional-reason>" }`

**Response**: `200 { "ok": true, "data": { id, ... } }` on success, `400 { "ok": false, "error": "<message>" }` if action is not pending or invalid input

## Deliberately out of scope

Face ID authentication, search endpoints — covered in separate tickets (#157, #160). This backend provides read-only access to dashboard data, managed session state with side-effecting permission gating, and the mobile client.

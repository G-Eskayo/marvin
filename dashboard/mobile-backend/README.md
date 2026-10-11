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

### `GET /mr/<owner>/<name>/<number>`

Fetch PR detail with embedded media metadata for mobile review.

**Path parameters**: `owner` (repository owner), `name` (repository name), `number` (PR number)

**Response**:
- `200 { "ok": true, "data": { number, title, url, repo, images: [{ url, kind, alt, group, caption }, ...], ticketRef: <number|null>, needsImages: { files } | null } }`
  - `images`: Parsed media from PR description (stills, GIFs, recordings)
  - `ticketRef`: Linked ticket number (from Closes/Fixes/Resolves in body)
  - `needsImages`: Object with `{ files }` if PR touches UI but lacks images in description, `null` otherwise
- `403 { "ok": false, "error": "Repository not authorized" }` — repo not in registry
- `500 { "ok": false, "error": "<message>" }` — gh execution failure

### `GET /mr/image?url=<encoded>&kind=<image|video|auto>`

Stream media bytes (images or videos) with HTTP Range support for seeking.

**Query parameters**:
- `url` (required): Media URL to fetch (validated against SSRF allowlist before any network fetch)
- `kind` (optional): `image`, `video`, or `auto` (default: `auto`)

**Response**:
- Image kind: `200 <binary> Content-Type: image/*; Content-Length: <n>; Accept-Ranges: bytes`
- Video kind: `200 <binary>` (full file) or `206 <partial>` (if valid Range header) with `Accept-Ranges: bytes` and `Content-Range: bytes <start>-<end>/<total>`
- `400 { "ok": false, "error": "Missing url parameter" }` — required parameter missing
- `416 { "ok": false, ... }` — Range out of bounds (invalid Range header on video file)
- `502 { "ok": false, "error": "<reason>" }` — media fetch failure (too large, not found, network error, host not allowed, etc.)

**Media validation**: URLs are validated against a GitHub-scoped allowlist before any network fetch (raw.githubusercontent.com, github.com, api.github.com, *.githubusercontent.com, github-production-user-asset-*.s3.amazonaws.com). Non-HTTPS, private-IP, and arbitrarily external URLs are rejected at the loader level.

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

## Dashboard write actions (confirmed-gated)

These endpoints handle side-effecting operations on dashboard items (tickets and PRs). All three require a `confirmed` flag (set to `true` by the mobile client after Face ID verification) — requests with missing or false `confirmed` return `403 { "ok": false, "error": "Confirmed action required" }` with no side effect.

### `POST /boards/ticket/reply`

Post a comment on a ticket and, if the ticket was waiting for owner input, re-queue it.

**Request body**: `{ "repo": "<repo>", "number": <ticket-number>, "body": "<comment>", "confirmed": true }`

**Response**:
- `200 { "ok": true, "data": { posted: true, requeued: <bool>, effect: "<description>" } }` on success
- `400 { "ok": false, "error": "<message>" }` on invalid input
- `403 { "ok": false, "error": "Confirmed action required" }` if `confirmed` is missing or false

### `POST /mr/approve`

Approve and merge a PR via the webhook-server.

**Request body**: `{ "pr_url": "<full-github-pr-url>", "confirmed": true }`

**Response**:
- `200 { "ok": true, "data": <webhook-response> }` on success (webhook response includes `merged`, `reengaged`, etc.)
- `500 { "ok": false, "error": "<message>" }` on webhook failure
- `403 { "ok": false, "error": "Confirmed action required" }` if `confirmed` is missing or false

### `POST /mr/deny`

Deny a PR with structured feedback (send feedback + re-engagement tag, or drop entirely).

**Request body**:
```json
{
  "pr_url": "<full-github-pr-url>",
  "ticket_number": <originating-ticket-number-or-null>,
  "action": "send_feedback" | "drop",
  "reasons": ["<reason>", ...],
  "comment": "<optional-freetext>",
  "confirmed": true
}
```

**Response**:
- `200 { "ok": true, "data": <webhook-response> }` on success (webhook response includes `done`)
- `400 { "ok": false, "error": "<message>" }` on invalid `action` or bad JSON
- `500 { "ok": false, "error": "<message>" }` on webhook failure
- `403 { "ok": false, "error": "Confirmed action required" }` if `confirmed` is missing or false

## Deliberately out of scope

Face ID authentication lives in the mobile client (iOS) per ADR 0043 — this backend only checks the `confirmed` flag it sets. Search endpoints are handled separately. This backend provides read-only access to dashboard data, managed session state with side-effecting permission gating, real-time updates, and the mobile client's write endpoints.

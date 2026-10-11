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

**Limitation**: Titles are fetched on-demand from GitHub for rows with `title: null` (best-effort; a missing ticket or GitHub outage leaves `title` as `null` rather than erroring the whole list).

### `GET /activity/timeline?number=<number>&repo=<repo>`

Fetch the stage-event timeline for a single ticket.

**Query parameters**: `number` (required), `repo` (optional, defaults to marvin)

**Response**: `200 { "ok": true, "data": [{ stage, status, timestamp, ... }, ...] }`

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

### `GET /boards/load?repo=<repo>`

Load a full board (columns, cards, cross-project issues).

**Query parameters**: `repo` (required, registered board repo)

**Response**: `200 { "ok": true, "data": { repo, columns: [{ id, title, cards, archive }], otherProjects: [{ projectId, count, repo, name }], fetchedAt } }`

**Limitation**: `reconciler.observe()` (Electron UI telemetry) is omitted; the data structure is otherwise identical to the desktop view.

### `GET /mr/list`

List open PRs across all registered repos with merge readiness, sent-back status, and rework tracking.

**Response**: `200 { "ok": true, "data": [{ number, title, url, repo, key, canMerge, conflicts, rebase, autoMerge, checks, sentBack, ticketRef, ticketClosed, rework, evidence, ... }, ...] }`

**Limitation**: One repo's GitHub outage does not hide other repos' PRs. `rebaseStatus` and `autoMergeShadow` degrade to `null` if the webhook endpoint is unavailable.

### `GET /mr/review-status`

Get the MR Review tab status (green/red/blue) and open PR count.

**Response**: `200 { "ok": true, "data": { status: "green" | "red" | "blue", openCount: <n> } }`

**Limitation**: Mobile clients see unseen PRs as red until a `/mark-seen` endpoint is added (out of scope for now). The mobile seen-state file is independent of the desktop's.

### `GET /mr/ticket-context?ref=<ref>&repo=<repo>`

Fetch a ticket and (if present) its parent PRD via the "## Parent" reference.

**Query parameters**: `ref` (required, ticket number), `repo` (optional, defaults to marvin, must be MARVIN_REPO or a registered board repo)

**Response**: `200 { "ok": true, "data": { ticket: { number, title, body, ... } | null, parent: { number, title, body, ... } | null } }`

**Limitation**: A missing or inaccessible ticket/parent comes back as `null` rather than erroring; the rest of the response is still valid.

### `GET /mr/detail?repo=<repo>&number=<number>`

Fetch a single PR with full detail (images, decisions, approval gating).

**Query parameters**: `repo` (optional, defaults to marvin, must be MARVIN_REPO or a registered board repo), `number` (required, numeric PR number)

**Response**: `200 { "ok": true, "data": { number, title, url, body, images: [{ url, kind, alt, group, caption }], headRef, baseRef, canMerge, needsImages, decisions: [{ title, outcome, reasons }], evidence, ... } }`

**Limitation**: Non-numeric `number` or unregistered `repo` returns `400`. PR not found or GitHub outage returns `502`.

### `GET /mr/media?url=<url>&kind=<kind>`

Stream media bytes (images or video) for a PR detail view.

**Query parameters**: `url` (required, full HTTPS URL to GitHub raw/attachment asset), `kind` (optional, `image`, `video`, or `auto` — usually `auto`)

**Response**:
- `200 <raw-bytes>` with appropriate `Content-Type`, `Content-Length`, `Accept-Ranges: bytes`, and `Cache-Control: public, max-age=31536000` — success (full file or no Range header)
  - For images: `image/png`, `image/jpeg`, `image/gif`, etc.; raw decoded bytes
  - For video: `video/mp4`, `video/quicktime`, etc.; full content
- `206 <partial-bytes>` with `Content-Range: bytes <start>-<end>/<total>` — successful Range request
  - For video: partial content matching the `Range: bytes=start-end` request header
- `400 { "ok": false, "error": "<message>" }` — missing/invalid `url`
- `404 { "ok": false, "error": "<message>" }` — asset not found or private-repo credential lacks access
- `416 { "error": ... }` with `Content-Range: bytes */<size>` — Range request out of bounds or malformed
- `502 { "ok": false, "error": "<message>" }` — asset too large or download/decode failure

**Range semantics**: Videos support HTTP Range requests for seeking. Omitting the `Range` header triggers a `200 OK` response with the full file. A `Range: bytes=start-end` header triggers a `206 Partial Content` response with the requested byte range (end-byte clamped to EOF if over-specified). A malformed or out-of-bounds `Range` header (start ≥ file size) triggers a `416 Range Not Satisfiable` response with the total file size in `Content-Range: bytes */<size>`.

**Semantics**: Private-repo assets (GitHub user-attachments, raw.githubusercontent.com) are fetched server-side using the shared GitHub credential; the token is never included in the response. Images are cached at `~/.claude/pr-media-cache` for reuse across requests. Videos are cached separately and streamed with HTTP Range support for seeking.

**Testability**: `createMrMediaRouter({ cacheDir, loader })` accepts optional parameters: `cacheDir` (defaults to `~/.claude/pr-media-cache`) and `loader` (defaults to `createImageLoader({ cacheDir })`). For testing, provide a fake loader that returns test data without network calls.

**Limitation**: `url` is validated against an allowlist (GitHub hosts); non-HTTPS or non-allowlisted hosts return `400`.

### `GET /activity/overview`

Activity overview per project (tickets in review, waiting on human, blocked).

**Response**: `200 { "ok": true, "data": { "owner/repo": { review: <n>, needsYou: <n>, blocked: <n> }, ... } }`

### `GET /relations/ticket?repo=<repo>&number=<number>`

Fetch relations (related tickets, PRs, docs) for a ticket.

**Query parameters**: `repo` (required), `number` (required, numeric)

**Response**: `200 { "ok": true, "data": { state: "UNKNOWN" | "..." , title: "<>" or "(not loaded)", tickets: [...], prs: [...], docs: [...], column: "..." } }`

**Limitation**: Unknown repos or non-numeric numbers degrade gracefully to `state: 'UNKNOWN'` rather than erroring.

### `GET /relations/context?project=<project>`

Fetch linkify context for a project (ADR reference paths, repo name).

**Query parameters**: `project` (required, project ID)

**Response**: `200 { "ok": true, "data": { project, repo: "owner/repo" | null, adrs: { number: "path/to/adr", ... } } }`

### `GET /queue`

Get dispatch queue status.

**Response**: `200 { "ok": true, "data": { queue: [...], running: [...], error: <message> | null } }`

**Limitation**: A queue service failure returns `{ queue: [], running: [], error: "<message>" }` (never an empty-queue-looking success).

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

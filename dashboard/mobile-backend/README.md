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

## Contract: Endpoints

All endpoints require device allowlist verification (see Device gate section). Requests from non-allowlisted peers get `403 { "ok": false, "error": "not allowlisted" }`.

### `GET /status`
Health check: service is up and listening.

**Response**:
- `200 { "ok": true, "status": "up", "uptimeSeconds": <n>, "version": "1.0.0" }` — success

### `GET /activity`
List all tracked ticket activity across projects.

**Response**:
- `200 [{ "repo": "owner/repo", "number": 42, "key": "owner/repo#42", "currentStage": "executing", "currentStatus": "passed", "costUsd": 0.15, "failed": false, "title": "...", "eventCount": 3, "lastEventAt": "2026-10-06T20:00:00Z", "isLiveNow": false }, ...]` — success

### `GET /activity/timeline?number=<n>&repo=<owner/repo>`
One ticket's full event timeline.

**Query parameters**:
- `number` (required): ticket number
- `repo` (optional): project repo (default: G-Eskayo/marvin for marvin tickets)

**Response**:
- `200 [{ "stage": "claimed", "status": "started", "timestamp": "2026-10-06T20:00:00Z", "detail": "", "machine": "device-id", "cost_usd": null, "title": "..." }, ...]` — success
- `400` — missing required parameters

### `GET /health`
Dashboard health status.

**Response**:
- `200 { "generated_at": "2026-10-06T20:00:00Z", "overall": "green|yellow|red|grey", "coverage": "...", "anomaly": "...", "checks": [...] }` — success

### `GET /boards`
List registered project boards.

**Response**:
- `200 [{ "repo": "owner/repo", "board": true, "due": "2026-10-30", "dueHard": false, "status": "active|recent|dormant|archived" }, ...]` — success

### `GET /boards/ticket?repo=<owner/repo>&number=<n>`
One ticket's detail.

**Query parameters**:
- `repo` (required): project repo
- `number` (required): ticket number

**Response**:
- `200 { "number": 42, "title": "...", "body": "...", "labels": [...], "url": "...", "state": "OPEN|CLOSED", "comments": 5 }` — success
- `400` — missing required parameters
- `404` — repo not registered in the board registry

### `GET /docs/repos`
List all documentation repositories and projects.

**Response**:
- `200 { "generated_at": "2026-10-06T20:00:00Z", "repos": [{ "id": "marvin", "name": "MARVIN", "kind": "repo", "status": "active", "local": null, "repo": "G-Eskayo/marvin" }, ...] }` — success

### `GET /docs/tree?id=<id>`
Documentation tree (files and structure) for one project.

**Query parameters**:
- `id` (required): project id

**Response**:
- `200 { "source": "local|github|card", "dir": null, "tree": [{ "path": "CONTEXT.md", "label": "Context" }, ...] }` — success
- `400` — missing required parameters

### `GET /docs/content?id=<id>&path=<path>`
File content from documentation.

**Query parameters**:
- `id` (required): project id
- `path` (required): file path (e.g., "CONTEXT.md")

**Response**:
- `200 <file content as text>` — success
- `400` — missing required parameters

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

## Deliberately out of scope

Face ID authentication, write endpoints, session rotation — covered in separate tickets (#159, #160, #157, #158). This ticket is the device gate and read-only status endpoint only.

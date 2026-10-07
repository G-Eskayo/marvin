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

## Contract: `GET /status`

**Response**:
- `200 { "ok": true, "status": "up", "uptimeSeconds": <n>, "version": "1.0.0" }` — allowlisted peer
- `403 { "ok": false, "error": "not allowlisted" }` — peer not in allowlist

## Contract: `POST /chat`

Streams a headless Claude Code session reply as NDJSON. Tracks the session ID internally to resume on the next request (single in-memory session; see #158 for durable persistence and rotation).

**Request**:
```json
{
  "message": "Your message to Claude"
}
```

**Response**:
- `200 application/x-ndjson` — stream of normalised events (one JSON object per line)
  - `{ "type": "session_start", "sessionId": "..." }`
  - `{ "type": "text_delta", "text": "..." }`
  - `{ "type": "tool_use", "toolName": "...", "toolId": "...", "toolInput": {...} }`
  - `{ "type": "result", "isError": false, "resultText": "...", "costUsd": 0.001, ... }`
  - `{ "type": "error", "message": "..." }`
- `400 { "error": "..." }` — invalid request (missing or empty message)
- `403 { "ok": false, "error": "not allowlisted" }` — peer not in allowlist

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

Face ID authentication, permission UI for tool approvals, session rotation, durable persistence across restarts — covered in separate tickets:
- #158: Thread persistence and session rotation
- #159: Permission bridge for tool approvals
- Other: Face ID, OAuth, etc.

This ticket (#157) covers just the streaming chat endpoint over one resumable in-memory session.

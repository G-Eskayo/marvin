# Mobile backend service

Standalone Node service that vets Tailscale device identity via allowlist and serves MARVIN Mobile: dashboard data, the Thread, the permission bridge and the voice endpoint. Runs under launchd supervision: restarts on crash, listens only on this machine's Tailscale IPv4 address.

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

## Voice endpoint (ADR 0075)

The one place spoken words reach MARVIN. The Siri doorway (HomePods), the Mac voice loop, the iPhone Voice surface
and any later endpoint (Apple TV, a Dot) all call it and name themselves in `source`. Every exchange lands in the
Thread with `source: "voice"` and `meta.device`, so a question asked on a HomePod shows on the phone.

### `POST /voice`

**Request body**: `{ "text": "<what was said>", "source": "homepod" | "mac" | "iphone" | "watch" | "appletv" | <registered>, "abilities"?: [...], "sttMs"?: <n>, "stream"?: true }`

- `source` must be a registered endpoint (below), or the request is refused (`403`, "unknown device"). This is on top
  of the Tailscale device gate, which every route already passes through.
- `abilities` can only narrow the registered ones. An endpoint without `show` never gets a `display` field.
- `sttMs`: the device's speech-to-text time, logged with the turn.

**Response (not streaming, for the Siri doorway)**: `200 { "ok": true, "data": { turnId, brain, speech, display?, pendingActionId?, deepPending?, timings } }`

- `speech` is always speakable: no Markdown, code or URLs, at most three sentences / 400 characters. A longer reply is
  cut at a sentence boundary with "I'll put the rest in the Thread on your phone", and the whole text goes to the
  Thread (and to `display` if the endpoint can show).
- `brain`: `fast` (the local model answered), `deep` (the Thread's MARVIN session) or `action` (a side effect, see
  below).
- `deepPending: true`: the deep brain didn't finish within 8 s. `speech` says the answer will come to the Thread,
  and it lands there when ready.

**Response (`stream: true`, for the Mac loop and the phone)**: `application/x-ndjson`, one event per line:
`{type:"turn", turnId, brain}`, then `{type:"sentence", text, holding?}` as each sentence finishes (a deep turn
starts with a holding line such as "Checking."), `{type:"pending", actionId, summary}` for an action, and finally
`{type:"done", speech, timings, ...}`.

**Errors are spoken too**: every refusal or failure carries a `speech` field ("I didn't catch anything", "I can't reach
my models right now"). The endpoint never answers with silence.

### Two brains

- **Routing** (`voice_router.js`): a side-effect request becomes an `action`. Otherwise the route classifier
  (`skills/route/scripts/route.py`, keyword pass, ~30 ms) picks the brain: zero-hit short small talk goes to the
  fast brain, and anything it recognises, anything long, or anything about MARVIN's state or the world right now
  (PRs, tickets, the board, weather) goes deep.
- **Fast brain** (`fast_brain.js`): `qwen2.5:3b` in Ollama, warmed at startup and kept loaded (`keep_alive` 60 min).
  Override the model with `MARVIN_VOICE_FAST_MODEL`. It replies `DEEP` to hand a turn up. If it is down or slow
  (no first token in 1.5 s), the turn goes to the deep brain.
- **Deep brain**: `claude -p` resuming the Thread's current Session, **read-only**: `--tools` and `--allowedTools`
  limited to Read, Grep, Glob, WebSearch and WebFetch, `--strict-mcp-config` (no MCP servers), `dontAsk`. It can look
  things up but cannot change anything.

### Side effects: the phone confirms (ADR 0005, ADR 0043)

Nothing with a side effect runs on a voice request alone, whatever the request body says (a `confirmed` flag in a
voice request is ignored). The reply is the plan ("I'd merge PR 657. Confirm on your phone."), and the request is
stored as a pending action with `toolName: "VoiceRequest"`. It shows in `GET /pending-actions`. When the phone
resolves it with Face ID through `POST /pending-actions/resolve`, `allow` runs the request as a normal Thread turn
(the same `claude -p` as Chat), and `deny` records the cancellation. A voice request that waits more than 15 minutes
expires and is not run.

### `POST /voice/timing`

**Request body**: `{ "turnId": "<from the turn>", "firstSoundMs": <n> }`. The device reports when it started speaking.

### Measurement

Each turn appends one line to `~/.claude/logs/voice-turns.jsonl`: `turnId, device, brain, sttMs, routingMs,
firstTokenMs, firstSentenceMs, totalMs, truncated, ok`. First-sound reports are added as their own lines, keyed by
`turnId`. The log holds timings only, never what was said.

### Endpoints registry

Built in: `homepod` (listen, speak), `mac`, `iphone`, `watch` (show, touch, listen, speak), `appletv` (show, listen,
speak). Add or change one in `~/.claude/voice-endpoints.json`, without a restart:

```json
{ "endpoints": { "kitchen-dot": { "abilities": ["listen", "speak"] } } }
```

## Deliberately out of scope

Face ID authentication lives in the mobile client (iOS) per ADR 0043 — this backend only checks the `confirmed` flag it sets. Search endpoints are handled separately. This backend provides read-only access to dashboard data, managed session state with side-effecting permission gating, real-time updates, and the mobile client's write endpoints.

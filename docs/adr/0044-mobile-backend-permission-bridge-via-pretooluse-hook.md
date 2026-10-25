# 0044 — Permission bridge via PreToolUse hook, not MCP permission-prompt-tool

## Status

Accepted (2026-10-07). Closes the open question in [[0040]].

## Context

[[0040]] identified that permission guardrails (per [[0005]]) must use the CLI's permission mechanisms
(hooks, not SDK callbacks) but marked the design open: "permission-prompt tool / hooks ... design still
open."

A prior rebuild attempt (commit 41dd652) tried to ship a hand-rolled MCP stdio server as the
"permission-prompt-tool," but that approach had fatal flaws:

1. The CLI has no `--permission-prompt-tool` flag; the phrase appears only in help text for
   `--permission-prompts` as something *the SDK host* provides. There's no way to wire it in.
2. The CLI's permission modes (`acceptEdits|auto|bypassPermissions|manual|dontAsk|plan`) don't include
   "default" — the prior attempt passed an invalid flag.
3. Timeouts relied on lazy eviction (checking expiry only on the next `list()` call), leaving
   promises hanging indefinitely if nobody polls.

The repo already runs successful precendent: `gh_merge_guard.py`, a **PreToolUse hook** that
semantically validates tool calls and returns `allow|deny` without needing any special CLI flag or
SDK hook. [[0030]] confirms per-invocation `--settings` (injecting hooks scoped to one session) works
safely in headless `-p` mode.

## Decision

Implement permission gating via:
- A `permissionBridge` module that tracks pending actions with **real `setTimeout` timers** (fixes
  timeout hang).
- A `permission_hook.js` script that runs as a PreToolUse hook: reads tool requests from stdin,
  POSTs to a **loopback-only relay server**, and writes the decision back to stdout. Fails closed
  (deny) if the relay is unreachable or times out (per [[0005]]).
- Per-invocation `--settings` flag injected into the CLI args when the bridge is provided, wiring
  the hook into that session only.
- A loopback HTTP relay server (127.0.0.1:7881) that the hook subprocess contacts to request
  permission and block until a decision arrives or the timeout fires.
- HTTP API routes (`GET /pending-actions`, `POST /pending-actions/resolve`) to list and resolve
  pending actions from the UI.

## Consequences

- Valid CLI flags and actual working timeouts: the prior MCP attempt's defects are fixed.
- Read-only tools (Read, Grep, Glob, WebSearch) auto-allow without creating pending actions.
- Side-effecting tool calls (Bash, Edit, Write, etc.) block the CLI subprocess until approved,
  denied, or the timeout (default 5 minutes) fires.
- Loopback-only relay is not on the device-gated Tailscale server — it is only reachable from
  processes on this machine, so the permission bridge is invisible to network clients. Same
  reasoning as the prior attempt: this is local plumbing between the backend and the CLI
  subprocess.
- Pending action shape includes a short summary (e.g., "Bash: rm -rf /" truncated to 60 chars)
  for UI display, avoiding full tool input round-trip.
- Usage counts against Gil's plan limits, shared with pipeline and interactive sessions ([[0040]]).

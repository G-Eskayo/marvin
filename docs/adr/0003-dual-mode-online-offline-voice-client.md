# 0003 — Dual-mode architecture: full MARVIN online, degraded local model offline

## Status

Accepted (2026-07-03)

## Context

Initial scope was "voice interface for MARVIN" assuming continuous connectivity back to a
backend (whether `remote-control` or, per [[0001]], the Agent SDK). Giles wants the assistant
to remain useful "off-grid to an extent" — specifically, true offline: no local network, no
cellular, nothing nearby to reach at all.

There is no way to preserve full MARVIN capability (skills, memory, tool execution, real
Claude model) with zero connectivity — that capability is inherently server-side. The only
way to offer *something* offline is a small local/open-weight model running directly on the
phone.

## Decision

The voice client operates in two distinct modes:

- **Online mode**: connects to the Agent SDK backend ([[0001]]) over the network (home
  network or Tailscale). Full MARVIN — real Claude model, skills, memory.
- **Offline mode**: no connectivity available. Falls back to a small local/open-weight model
  running on-device (see [[0002]] — this is why the client must be native, not a PWA).
  Conversational only; no MARVIN skills, no memory read/write, no tool execution.

The client must detect connectivity and switch modes automatically.

## Consequences

- Offline mode is a materially dumber assistant than online mode — this is an accepted,
  explicit trade, not a bug to fix later.
- Still open: which local model to run on-device, how (or whether) anything captured in
  offline mode reconciles with MARVIN's real memory once back online, and whether offline
  mode gets any slice of MARVIN's skills/context as a system prompt versus being a bare
  local-model chat.
- Reinforces [[0002]]'s native-app requirement — this decision is the actual reason a PWA was
  ruled out, not app polish.

# 0001 — Use the Claude Agent SDK, not `remote-control`, as the voice client's backend

## Status

Accepted (2026-07-03)

## Context

The voice interface needs a custom client (phone-side audio in/out) talking to a real MARVIN
agent session. Claude Code's `remote-control` feature was the obvious starting point — it
already works for phone↔desktop sessions (paired successfully earlier this session) and even
exposes a `--permission-mode plan` flag that looked like a ready-made safety guardrail for a
voice-driven session.

Researched whether a custom client could be built against `remote-control`'s pairing protocol.
Finding: that protocol is undocumented and private — it exists only to serve Anthropic's own
official clients (the mobile app, claude.ai/code web UI), routes through Anthropic's
infrastructure with short-lived scoped credentials, and has no published spec or SDK. Building
against it would mean reverse-engineering an undocumented protocol: fragile (silent breakage on
any Anthropic-side update) and against Anthropic's terms of service.

The Claude Agent SDK, by contrast, is a documented, versioned, public API explicitly intended
for building custom agent clients — session management, tool execution, streaming
input/output.

## Decision

Build the voice client's backend on the Claude Agent SDK, standing up a dedicated agent backend
process (on a machine already in MARVIN's Tailscale network) rather than attempting to interface
with `remote-control`.

## Consequences

- Lose the free ride of `remote-control`'s existing pairing/UI — must build session
  management, auth, and streaming ourselves on the Agent SDK.
- Gain a stable, supported foundation instead of a reverse-engineered one.
- The `--permission-mode plan` guardrail idea doesn't carry over as-is; an equivalent
  tool-execution safety mechanism needs to be designed against the Agent SDK's own
  permission model (open question, not yet resolved as of this ADR).

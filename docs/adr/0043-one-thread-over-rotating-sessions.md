# 0043 — Chat and Voice share one continuous Thread backed by rotating, terminal-resumable Sessions

## Status

Accepted (2026-10-05)

## Context

MARVIN Mobile needs a conversation model for Chat and Voice. Options: one continuous Thread
(messaging-app style); a list of separate conversations (Claude-app style); and exposing phone
conversations as resumable Claude Code sessions. A list adds friction on every interaction and
gives proactive messages nowhere natural to land. A single unbounded Claude session would grow
until context quality degrades.

## Decision

Gil sees one Thread shared by Chat and Voice, where proactive messages also arrive. Behind it,
the backend rotates the underlying headless Claude Code Session ([[0039]]) on topic shift or
length, carrying a short summary forward (same idea as the handoff skill). Each Session is a
real Claude Code session, resumable from a terminal with `claude --resume`.

## Consequences

- Zero-friction UX: open the app and talk; no conversation management.
- Rotation needs a heuristic (topic shift / length) — a wrong cut loses some nuance across the
  summary boundary. Tuning is expected.
- The backend must map Thread messages ↔ Session IDs so terminal resume can find the right
  Session from a point in the Thread.
- Phone-originated Sessions mix into the normal `~/.claude` session history on the Mac Mini.

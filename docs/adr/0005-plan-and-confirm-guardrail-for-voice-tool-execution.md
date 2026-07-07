# 0005 — Plan-and-confirm guardrail for voice-triggered tool execution

## Status

Accepted (2026-07-03)

## Context

`--permission-mode plan` was flagged back when the voice interface was assumed to ride on
`remote-control` ([[0001]] superseded that assumption) as the mechanism for a real, stated
problem: you can't visually review a diff or a Bash command when the whole interaction is
spoken. The Agent SDK has its own permission model instead of that flag, so an equivalent
policy needs to be defined explicitly for it.

Considered: read-only-by-voice (safest, but voice can't actually get anything done),
plan-and-confirm (read tools run freely, anything with side effects gets described aloud and
requires explicit confirmation before executing), and full trust (no gate).

MARVIN's existing background self-improvement reviewer solves a superficially similar problem
(tool restriction as the sole safety boundary) but for a headless, unattended process — nobody
is present to confirm anything there, so restriction has to be the whole guardrail. A voice
session is the opposite: Giles is live and present. A confirm-before-execute step is usable
here in a way it isn't for that unattended case.

## Decision

Read/search tools (Read, Grep, WebSearch, etc.) execute freely. Any tool with side effects
(Write, Edit, Bash, etc.) must be described aloud via TTS as a proposed action and wait for an
explicit verbal or tap confirmation before running.

## Consequences

- Voice sessions can actually make changes, unlike a pure read-only policy — but every
  side-effecting action costs a confirmation round-trip, adding latency/friction to voice
  interactions that involve real work.
- Needs a concrete implementation: an Agent SDK permission callback that blocks pending tool
  calls until a confirmation signal arrives, plus a TTS-friendly way to summarize a pending
  diff/command (not yet designed).
- Does not apply to offline mode ([[0003]]) as currently scoped — offline mode has no tool
  execution at all (conversational only), so this guardrail is an online-mode-only concern
  for now.

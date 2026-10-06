# 0045 — Offline mode uses Apple's Foundation Models framework; MLX is the fallback

## Status

Accepted (2026-10-05). Supersedes [[0006]]; reopened by [[0039]].

## Context

[[0006]] chose MLX Swift + a downloaded 4-bit open-weight model for offline mode ([[0003]]),
written before Apple's Foundation Models framework (iOS 26) was a practical option. Target device
is now concretely an iPhone 17 Pro on iOS 26 ([[0039]]).

Foundation Models: zero download, native Swift with tool calling and guided (structured) output,
Apple-maintained — but Apple controls the model and its updates, and its context window is small.
MLX: pick and pin any open-weight model, larger context — but multi-GB app payload, model
management, and less-proven on-device iOS maturity (0006's own stated risk).

Offline mode is explicitly the degraded, conversational-only tier ([[0003]]), so peak model
quality matters less than zero-friction availability.

## Decision

Use Apple's Foundation Models framework for offline mode and small on-phone tasks. Keep MLX +
open-weight as the documented fallback if Foundation Models proves too weak in practice.

## Consequences

- No model download; app stays small; nothing to update or store.
- Offline behaviour can shift when Apple updates the system model with an iOS release — ties into
  the planned iOS-update maintainer agent idea.
- Small context window: offline mode can't carry much of the Thread; it sees only recent turns.
- The roadmap §A Int4/quantization item that 0006 activated goes back to parked unless the MLX
  fallback is triggered.

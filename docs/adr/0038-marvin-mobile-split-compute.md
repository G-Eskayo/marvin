# 0038 — MARVIN Mobile splits compute: speech + offline on the phone, thinking on the Mac Mini

## Status

Accepted (2026-10-05)

## Context

MARVIN Mobile (see CONTEXT.md) folds July's voice client ([[0001]]–[[0006]]) and the roadmap's
WhatsApp/Telegram companion into one native app with three surfaces: Voice, Chat, Dashboard.
Target device is Gil's iPhone 17 Pro on iOS 26, which has two capable on-device engines:
`SpeechAnalyzer` (on-device speech-to-text, already proven in clarity-captions) and Apple's
Foundation Models framework (a ~3B on-device model callable from Swift, no download).

Considered:

- **Everything on the Mac Mini** — phone is a thin client streaming audio. Simplest, but wastes
  the phone's hardware, sends audio over the network, and does nothing offline.
- **Everything on the phone** — impossible for full MARVIN: skills, memory, files and tools
  live on the Mac Mini, and a ~3B model can't plan or reason across projects like Claude.
- **Split** — chosen.

## Decision

The phone owns speech-to-text, text-to-speech, offline mode, and small local tasks (summarising
a notification, shaping an utterance before sending). The Mac Mini's mobile backend owns real
reasoning (Claude), skills, memory, tool execution and dashboard data. Only text crosses the
Tailscale link, never raw audio.

## Consequences

- Speech works with zero usage cost and low latency; less data on the wire; audio never leaves
  the phone.
- Voice can reuse clarity-captions' `SpeechAnalyzer` learnings directly.
- Reopens [[0006]] (MLX for offline mode): Apple's Foundation Models framework, which didn't
  exist when 0006 was written, is now a plausible zero-download alternative. Not decided here.
- Two inference stacks to maintain (on-device Apple frameworks + Claude on the Mac), and the
  app must decide per request which side handles it.
- Requires iOS 26 + an Apple-Intelligence-capable iPhone; fine for a single-user app.

# 0002 — Native iOS app, not a PWA, for the voice client

## Status

Accepted (2026-07-03)

## Context

Two shells were considered for the phone side: a PWA ("Add to Home Screen" web app, no
distribution overhead, TTS works fine in iOS Safari but live in-browser STT is unreliable/
unsupported), and a native app (full platform capability, but real distribution cost — either a
free Apple ID with a 7-day resign cycle, or a $99/yr Developer account).

The PWA route remained viable — server-side STT (upload a recorded clip, transcribe on the
backend) sidesteps iOS Safari's missing `SpeechRecognition` support without much extra work,
since that backend has to exist anyway for the Agent SDK integration ([[0001]]).

That calculus changed with the decision to support a true **offline mode** ([[0003]]):
on-device model inference for a fully disconnected phone requires direct access to the
device's Metal/CoreML compute and the ability to bundle/run multi-gigabyte model weights
locally. A PWA running in Safari cannot do this — there is no browser API for local LLM
inference at that scale. Offline mode is only possible from a real native app.

## Decision

Build a native iOS app. Accept the distribution cost (Apple Developer account status still
open, see main conversation) as a necessary consequence of the offline-mode requirement, not
of a "nicer app" preference.

## Consequences

- Full Xcode/Swift build, app lifecycle, and signing/distribution overhead that the PWA route
  would have avoided.
- Unlocks on-device model inference for offline mode ([[0003]]), which was the actual reason
  this was worth the cost.
- Distribution mechanism (sideload vs paid Developer account vs TestFlight) still needs to be
  decided.

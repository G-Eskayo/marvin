## `deep-latency`: confirmed as-built, nothing changed

The race condition and fallback path remain unchanged on `origin/voice-endpoint-670`:

- `dashboard/mobile-backend/voice_api.js`, lines 118-119: `deepWaitMs ?? 8000` and `deepStreamMaxMs ?? 120000` define the race.
- Lines 192-194: `deepPending` thread fallback when deep completes too slow.

This was already the as-built default before your decision. Nothing to build.

## `deep-tools`: no chosen option; still open for you

The note ("I want it to be interactive like a lab assistant...") is a direction, not a tick. Per `docs/agents/decisions-format.md` ("Don't answer the questions yourself... don't pre-tick a box unless it records an answer the owner already gave"), nothing is built for `deep-tools`.

The question stays open in the PR body for whenever you're ready to choose. The broader "lab assistant / human-readable reporting" work belongs with ADR 0085's front-desk direction, as that becomes concrete enough for real options.

## Earlier answers: all kept

Each of the 5 docs in the ticket's "Earlier answers" list cites #670 as a roadmap pointer only, never restates either decision. Each is kept explicitly:

- `dashboard-ux-potholes-2026-10-29.md`: roadmap reference.
- `marvin-business-plan-2026-10-25.md`: roadmap reference.
- `marvin-website-2026-11-02.md`: roadmap reference.
- `project-homepod-appletv-spike.md`: roadmap reference.
- `project-investor-demo-plan.md`: roadmap reference.

## Screenshots: no UI/visual surface to retake

This PR has no UI changes — nothing to capture or pin.

<!-- marvin:decisions-addressed -->

<!-- excerpt of G-Eskayo/clarity-captions PR #181 body (first body, before it was fixed), trimmed to its Decisions section -->

## Decisions

1. **How should the Listening light breathe?**
   - **A. Gentle (recommended)**: one slow breath every 2.4 s, fading about halfway toward the background. Calm enough to ignore at the dinner table, and still clearly alive.
   - **B. Steady**: one breath every 1.4 s, fading deeper. Easier to notice, but busier.
   - **C. Follows the room**: no timer. It's brighter when people are talking and softer when it's quiet (what the grey dot does today, but in red). This also tells her something, but in a quiet room it sits soft and can look off.
2. **Icon buttons (gear, saved list, close, back)**: is dim plus a small give (shrinks to 88%) right? Other choices are dim only, or no change.
3. **Stop circle**: is darken plus a small give (shrinks to 92%) right? Or darken only?
4. **Mac hover**: a soft round highlight behind icons, as shown. Should the pills also brighten slightly on hover?
5. **Code location**: the light's colours and timings live in CaptionCore (`ListeningLight`), so the Mac app draws the identical light. The button styles are SwiftUI views in the iPhone app for now. Once approved I'll move them where the Mac build (#172) can use them too. OK?

## How it was made

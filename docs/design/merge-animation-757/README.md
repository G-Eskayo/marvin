# MR Review merge motion: mock-up (marvin#757)

**Status: mock-up for approval. The real dashboard is unchanged.** Once the owner answers the Decisions on the PR,
the motion gets built into `MrReview.jsx` / `MrHistory.jsx`, and `merge_motion.js` moves to `dashboard/src/lib/`.

## Run it

Open `index.html` in Chrome (straight from Finder; no server, no build). Pick a scene and press **Play**, or drag the
scrubber to step through it. Use the controls to switch between dark and light, normal and Reduce Motion, and the
alternative for each decision. Reduce Motion starts on if macOS has it on.

## The scenes

| # | Scene | What it shows |
|---|---|---|
| 1 | `single` | Leaving Open: the blue band crosses the card right to left, the card follows it out left with a light trail, the cards below close the gap |
| 2 | `detail` | You're inside the MR when it merges: a plain "✓ Merged" line replaces the buttons; the slide-out plays when you go back |
| 3 | `arrive` | Arriving in Merged: a space opens at the top and the row slides in from the right |
| 4 | `split` | Open beside Merged: out of Open to the right, a moment later into a space at the top of Merged |
| 5 | `batch` | Three merges at once (cascade, one-at-a-time, together) |
| 6 | `revert` | GitHub refuses a merge the screen already showed: the card comes back, amber pulse, "GitHub disagreed" notice |
| 7 | `scrolled` | Scrolled far down: a card above you leaves silently and your place holds; one on screen plays as usual |
| 8 | `away` | Back after the dashboard slept: the result with a count, or a replay |
| 9 | `swipe` | A swipe back (#756) half-way through |

## How it's made

- `merge_motion.js` holds the choreography with no DOM: every motion is a list of named phases (`sweep`, `slide`,
  `trail`, `close`, `gapOpen`, `arrive`, `fade`…) with start and end times, plus the edge-case rules (batching,
  deferral while you're elsewhere, scroll anchoring, swipe interrupts, refusals). Tests are in
  `dashboard/test/merge_motion_proto.test.js`. They check the order of the phases (the gap closes only once the card
  has mostly gone) and that nothing moves under Reduce Motion.
- `index.html` draws each frame as a pure function of time, so live play, the scrubber and the recording all match.
- `record.mjs` seeks frame by frame in headless Chrome at 25 fps, and ffmpeg builds one 2×2 GIF and MP4 per scene
  (dark | dark Reduce Motion / light | light Reduce Motion), plus one GIF per alternative:
  `node docs/design/merge-animation-757/record.mjs <outDir> [scene …]`.

## The blue

The sweep uses the website's brand blue `#198fd9` (gileskayo.me `brand.css` `--blue`) with the live site's focus-glow
halo, `0 0 8px rgba(102, 175, 233, .6)` (`main.css`). The Seal Speak site has no blue glow (its glows are teal,
`#1F998B` / `#4FB3A9`), so the halo comes from gileskayo.me.

## Light theme

The dashboard is dark-only today (`tailwind.config.js` `darkMode: 'class'`, and nothing sets a light theme). The light
recordings show how the motion would read if a light theme is added. They aren't a proposal to add one.

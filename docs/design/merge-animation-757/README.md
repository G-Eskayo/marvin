# MR Review merge motion: mock-up (marvin#757)

**Status: approved (round 2, PR #761) and built (marvin#838).** This folder is the round-2 mock-up as approved, kept
so it still opens from Finder. Its `merge_motion.js` is frozen at round 2. The live choreography, with the owner's
round-2 answers applied (0.8x faster, everything left to right, the check mark, the chips), is
`dashboard/src/lib/merge_motion.js`, tested in `dashboard/test/merge_motion.test.js`, played by
`dashboard/src/components/MergeMotion.jsx`. Motion is vendored for the app at `dashboard/src/vendor/`.

## Run it

Open `index.html` in Chrome (straight from Finder; no server, no build). Pick a scene and press **Play**, or drag the
scrubber to step through it. Switch between dark and light, and normal and Reduce Motion. Reduce Motion starts on if
macOS has it on. There are no other switches: the owner picked one answer for each round-1 question.

## The motion

- **Direction tells the story.** A card leaves Open left to right, and a new MR comes into Open left to right too. On
  the Merged tab the card arrives right to left, so leaving one list and arriving in the next reads like turning a
  page. In the split view it comes into Merged from the left instead, so it reads as one trip across the window.
- **In place.** Leaving: a solid blue fill crosses the card, and the closing sweep follows a third of a card behind it
  and leaves the space empty. The card never slides. Once the sweep is done, the cards below fall together.
- **Coming in** is the mirror: a space opens where the card belongs, the fill sweeps across it, and the card shows
  behind the fill.
- **About 1.3x slower** than round 1: a single merge takes about 1.5 s.
- **Nothing plays until GitHub confirms the merge.** While it waits the card shows the merge progress bar it shows
  today. A refusal leaves the card where it always was.
- **One at a time, in the order GitHub confirms them**, each in full with its gap closed before the next.
- **Reduce Motion:** fade, then the gap closes with a 0.2 s move. Coming in: the space opens in 0.2 s, then a fade.

## The scenes

| # | Scene | What it shows |
|---|---|---|
| 1 | `single` | Leaving Open: the fill and the closing sweep, in place, then the gap closes |
| 2 | `incoming` | A new MR comes in: the space opens where it belongs, the fill sweeps it in |
| 3 | `hold` | Approve: the card waits with its merge progress until GitHub confirms, then the sweep plays |
| 4 | `refused` | GitHub refuses: the card never moved; the existing "GitHub disagreed" notice says why |
| 5 | `detail` | Inside the MR when it merges: a plain "✓ Merged" line; the sweep plays when you go back |
| 6 | `arrive` | Arriving in Merged: a space opens at the top, the fill sweeps the row in from the right |
| 7 | `split` | Open beside Merged: out of Open left to right, a moment later into Merged from the left |
| 8 | `queue` | Three merges confirmed out of list order: one at a time, in confirmation order |
| 9 | `reverted` | A revert PR merges; the original's Merged row gets a "reverted by #N" tag |
| 10 | `scrolled` | Scrolled far down: a card leaving above you and one coming in above you both keep your place |
| 11 | `away` | Back after the dashboard slept: the result, with "N merged while you were away" |
| 12 | `swipe` | A swipe back (#756) half-way through: the animation finishes at once |

The dashed labels in the corners of the recordings are notes for whoever watches (the theme and motion setting, and
what GitHub just did). They aren't dashboard UI.

## How it's made

- `merge_motion.js` holds the choreography with no DOM: every motion is a list of named phases (`fill`, `clear`,
  `reveal`, `close`, `gapOpen`, `fade`, `fadeIn`) with start and end times, plus the rules: where a new card goes
  (`placeOf`), the queue in confirmation order (`planQueue`), the GitHub confirmation gate (`onMergeEvent`), holding a
  merge while you're elsewhere (`routeMerge`, `onListShown`), scroll anchoring both ways (`scrollPlan`) and the swipe
  interrupt. Tests are in `dashboard/test/merge_motion_proto.test.js`.
- `index.html` draws each frame as a pure function of time, so live play, the scrubber and the recording all match.
  Its easing comes from Motion (motion.dev) 14.8.0, vendored as `vendor/motion-14.8.0.js` (MIT, `vendor/motion-LICENSE.md`):
  the gap opens and closes on a Motion spring with no bounce, and the sweep uses Motion's `easeInOut`. A spring sampled
  at a given time is still a pure function of that time, so seeking works.
  The band's two edges come from one eased trip, so it stays a third of the card wide all the way across.
- `record.mjs` seeks frame by frame in headless Chrome at 25 fps, and ffmpeg builds one 2×2 GIF and MP4 per scene
  (dark | dark Reduce Motion / light | light Reduce Motion): `node docs/design/merge-animation-757/record.mjs <outDir> [scene …]`.

## The blue

The fill uses the website's brand blue `#198fd9` (gileskayo.me `brand.css` `--blue`) with the live site's focus-glow
halo, `0 0 8px rgba(102, 175, 233, .6)` (`main.css`).

## Light theme

The dashboard is dark-only today (`tailwind.config.js` `darkMode: 'class'`, and nothing sets a light theme). The light
recordings show how the motion would read if a light theme is added. They aren't a proposal to add one.

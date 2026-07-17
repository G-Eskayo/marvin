# brain-map GIF capture experiments (paused 2026-07-17)

Six iterations toward a rotating-brain-map GIF for the marvin repo's README.
Paused in favor of exploring an SVG-animation alternative — kept here in case
that doesn't pan out and this gets picked back up. `v6` is the most complete;
earlier versions are kept only because each one fixed a real bug in the last.

Run any of them against a local `python3 -m http.server` serving `brain-map/`,
e.g. `python3 -m http.server 8791` from `~/.agents/brain-map`, then the script
hits `http://127.0.0.1:8791/index.html?wallpaper=1`.

## Key findings, so the next attempt doesn't re-discover these

- **GitHub README content column is exactly 838px CSS-wide**, regardless of
  viewer's browser window size (verified 1280–2560px). 2x (1676px) for retina
  crispness costs ~72MB for a 489-frame/38s loop; 1x or ~1.5x (1256px, ~43MB)
  is more reasonable.
- **Camera easing is gated on `!dragging`.** Simulating rotation via mouse
  drag silently disables `nudgeCameraAndPulse`'s ease-toward-active-node
  behavior. Use the `window.setYaw(v)` / `window.getYaw()` hooks (added to
  template.html) instead — they don't touch `dragging`.
- **Headless Chromium's rAF ran at ~30fps effective here**, not 60fps — native
  auto-rotate (0.0008 rad/frame) took ~260s/full circle, not the ~131s a
  60fps assumption predicts. Don't hardcode a duration; measure.
- **Exact seamless loop recipe**: drive a pure-rotation segment via `setYaw`
  across exactly 2π in N deterministic steps (fast, no wall-clock cost, no
  jitter) for the "tour"; let a second segment run native autoRotate +
  pulses/easing for the "showcase"; then scan the tail of that second segment
  for the frame whose yaw is closest (mod 2π) to the start — a sub-1° match
  usually turns up within 15–20s of tail.
- `page.evaluate()` in Playwright Python takes exactly **one** arg value —
  pass multiple as a single list/dict, not extra positional args.
- `demoAddNode`'s nested children need an explicit `"children": []` on every
  leaf — `indexTree()` assumes it unconditionally (real tree data always has
  it; hand-built synthetic nodes for a demo don't unless you add it).
- **GIF file size is dominated by frame count** (fps × duration), not the
  declared fps metadata — dropping the fps number alone doesn't shrink a file
  built from the same frames.
- ffmpeg `colorkey` (near-black bg) + `palettegen reserve_transparent=1` +
  `paletteuse alpha_threshold` gives clean transparency; `gifsicle -O3
  --lossy=N` only helps marginally on glow-heavy content like this.
- Safari appeared to fail rendering large (40MB+) local `file://` GIFs
  (broken-image icon) even though the same file renders fine in Chromium —
  never root-caused; workaround was serving over local `http://` instead, or
  just previewing in Chromium directly. Preview.app never animates GIFs at
  all (first frame only) — always verify in a real browser.

# Animation tools evaluation — 2026-07-17

Catalogued at Gil's request after a live debugging session on `brain-map`'s
rotation/containment code, where the current hand-rolled easing (fixed-rate
lerps for `fitScale` and camera nudging) was starting to show its limits.
Scope: what each tool actually is, whether it fits `brain-map`'s rendering
model, and concrete recommendations — not just a links list.

## `brain-map`'s actual constraint, which shapes every recommendation below

`template.html` is a single static file with **no build step**, loaded three
ways: `file://` inside DesktopLive's WKWebView (desktop wallpaper, no
guaranteed network), a plain `http://` static serve (GitHub Pages / local
testing), or opened directly in a browser. Any tool brought in has to:

1. Work as a plain `<script>` tag — no npm/webpack/bundler in this pipeline.
2. Be vendored **locally** (a downloaded file in `brain-map/`), not loaded
   from a live CDN — DesktopLive must keep rendering with no internet
   connection, and a CDN 404/timeout shouldn't be able to blank the wallpaper.
3. Drive **values**, not markup — the actual rendering is 100% custom
   Canvas2D (`ctx.arc`, `ctx.stroke`, manual 3D→2D projection in `project()`).
   Nothing here renders DOM/CSS/SVG for us; at most a library can compute
   *numbers* (an eased position, a spring-settled scale) that our own
   `draw()` then paints by hand.

That third point is the one that rules two of the five tools out immediately.

## Anime.js — recommended, targeted use

24.5KB, framework-agnostic, animates arbitrary JS values (not just
DOM/CSS/SVG). UMD build works as a single `<script src>` tag:
`anime.umd.min.js` → global `anime`, `const { animate } = anime;`.

**Where it would genuinely help:**
- **`activePulses` (skill-activity pulse rings) and node grow/shrink on
  create/remove** — these are *already* exactly "animate a scalar over a
  duration with an easing curve," just hand-implemented (`activePulses`
  array + manual `t < 0.1 ? t/0.1 : Math.exp(-4*(t-0.1)/0.9)` in
  `pulseIntensityOf`). Anime's Timeline/stagger API is built for precisely
  this — and its **staggering system** is the direct answer to the paused
  GIF-experiment goal of a "dense multi-node activity cascade": stagger a
  batch of node reveals with one call instead of hand-tracking offsets per
  node.
- **`fitScale`'s asymmetric snap-down/relax-up response** (just built this
  session, see `template.html`) — currently two hardcoded lerp rates (9/sec
  down, 1.1/sec up). A real spring (anime's spring easing, or see Motion
  below) would settle more naturally than a fixed-rate lerp, especially the
  "relax back up" side, which currently can look slightly mechanical.

**What it would *not* help:** the actual lag. Anime.js computes numbers; our
own `ctx.clearRect` + per-shape `shadowBlur` + full-canvas
`mix-blend-mode: screen` overlay is what's expensive, at up to 2x DPR on
Retina displays. Swapping the lerp math for a library doesn't touch that.

## Motion (motion.dev, ex-Framer Motion) — recommended, targeted use

Real spring-physics math (not an approximation), plus gesture/scroll/layout
animation aimed mostly at DOM. Ships a dedicated **vanilla, non-React** build
specifically for this: the HTML/SVG bundle is **2.3KB minified**, script-tag
usable (`const { animate } = Motion`), no bundler.

**Where it fits:** same two spots as anime.js above (pulse timing,
`fitScale` spring), but Motion's spring implementation is the more direct,
purpose-built option if the goal is specifically "make the containment
response feel like a real spring, not two lerp rates." Anime.js's spring
easing is a curve *approximating* spring motion; Motion's is a literal
integrated spring simulation. For a single settle-into-place value like
`fitScale`, that's the more honest fit.

**Recommendation if choosing one over the other for the `fitScale`/pulse
work specifically: Motion**, for genuine spring accuracy and the smaller
footprint (2.3KB vs 24.5KB) — pull in anime.js *additionally* only if/when
the staggered multi-node cascade effect gets revisited, since that's
anime.js's stronger, more explicit feature (Motion's stagger support exists
but is secondary to its spring/gesture focus).

## Kokonut UI — catalogued, not usable as-is

100+ pre-built **React** UI components (Tailwind + shadcn + Motion
underneath). This is a component library for building React app UIs
(buttons, cards, dashboards) — it doesn't export raw Canvas2D drawing
primitives or standalone animation logic separable from its React
components. Nothing here is directly importable into a vanilla-JS
`file://` page with no React runtime.

**Retained for:** style/interaction-pattern reference (e.g. how they handle
hover/press micro-interactions, card-flip effects) if `brain-map` or a
future MARVIN surface ever becomes a React-based UI. Not actionable today.

## Bklit — catalogued, not usable as-is

React chart-component library (area/bar/pie/radar/candlestick, 17+ chart
types) for standard business data visualization. Same DOM/React constraint
as Kokonut UI, and conceptually a different problem — these are flat 2D
business charts, not a rotating 3D-projected node graph.

**Retained for:** reference if MARVIN ever needs a conventional 2D
chart/dashboard (e.g. a metrics view for `marvin-bench` results, cron-health
trends over time) — that's a much closer match to what Bklit actually does
than anything in `brain-map`.

## Manus (manus.im) — different category entirely

Not an animation library — a general-purpose autonomous AI agent (plans,
codes, and ships full-stack apps/websites from a prompt, credit-based
subscription, now part of Meta). Doesn't belong in the same evaluation as
the four tools above; noting it here only because it was included in the
same request.

**Retained for:** if there's ever a want for a second, independent
autonomous-agent opinion/comparison point against MARVIN's own
architecture — that's the only axis it's relevant on, not animation.

## Bottom line / recommended next step

If picking up the animation-quality thread: bring in **Motion's vanilla
HTML/SVG build** (2.3KB, vendored locally in `brain-map/`) to drive
`fitScale`'s spring response and the pulse-ring timing, since those are
already scalar-value animations wearing hand-rolled clothes. This is a
small, scoped change — not a rendering-architecture change — and won't
touch or fix the separate lag investigation (DPR/shadowBlur cost), which
stays a distinct thread. Anime.js is the second pull, specifically when/if
the staggered multi-node cascade effect from the paused GIF work gets
revisited.

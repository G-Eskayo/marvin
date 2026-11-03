# Plan usage and the one throttle switch (marvin#872), mock-up

**Status: mock-up for the owner's sign-off. The real dashboard (`dashboard/src`) is unchanged.**

Gil, 2026-11-03: "we need a way to monitor that in the dashboard probably in either vitals or workshop and if we do it
in workshop we could probably fold it in with the throttle trigger we still need to redo. I think the current UI/UX is
lacking and I was really just hoping for a toggle switch and the hope was that we have optimized our system enough to
throttle on an off with gaurdrails".

## What it shows

One card, two levels (one control per level):

1. **The row:** the **Auto throttle** switch, a headline saying what it is doing ("Full power · up to 4 at once",
   "Throttled at the soft line · background paused", "Holding new work · resets 16:10"), a line saying what flipping
   it would do *before* you flip it, and two small meters (5-hour window, week). **Details** opens level 2.
2. **Details:** the plan's 5-hour window and week against the soft (90) and hard (99) lines, the week's pace
   (the diamond is where it lands at the reset), the last 7 days window by window (used, hit the limit, left unused,
   and how much was left on the table), what it is doing now, and the guardrails that stay on either way.

The header carries the #905 throttle badge while throttled.

**Where:** Workshop ▸ Now (main option, folded with the switch), or Vitals ▸ Flow budgets (alternative: Vitals shows
the budget, the switch stays in Workshop). Switch with "Where" at the top.

## What it replaces

`dashboard/src/components/ParallelToggle.jsx`, mounted on the Activity tab (`ActivityBoard.jsx`), not in Health or
Workshop as Workshop's footer says. It is an On/Off pill plus two number boxes (tickets at once, per project) and a
Scan now button: four controls on one level. It switches between one per Mac and fixed caps from
`config/dispatch.json`, never adapts, shows no plan usage, doesn't say what is holding it back, and its cost note is a
fixed "$1.39 per ticket". The disk and GitHub guards it obeys are invisible.

## Open it

Inside MARVIN: the PR's **Try the mock-up** button (MR Review, #938), or `marvin-show
docs/design/872-usage-toggle/index.html --pr 1041`. Scenes and places link: `index.html#scene=hard&place=vitals&open=1`.

| Scene | What it shows |
|---|---|
| clear | On, plenty of room: full power |
| soft | 5-hour window 91%: background pauses, builds move to a cheaper model |
| warn | 96% and the week over pace: sessions ask before big work, queued work slows |
| hard | 99%: nothing new starts, builds finish, the repair still runs; flipping changes nothing until the reset |
| off | Off: one ticket at a time per Mac, lines and guards still apply |
| nodata | No reading yet: "not enough data yet", never 0%, one per Mac |
| stale | Reading 3 h old: keeps the last known step, meters dimmed |

The switch and Details are clickable in every scene. The dashed controls and the caption are notes for the reviewer.
`node docs/design/872-usage-toggle/shoot.mjs <outDir>` takes the PR's screenshots.

## How it's made

- `usage_toggle.js` is the whole rule, no DOM: `describeThrottle({ usage, on, running, queued, slots, guards,
  lastStep, now })` returns the step, both budgets, pace, windows, headline, what it's doing, the guardrails and the
  flip line. The page calls it on every click. Tests that try to break it:
  `dashboard/test/usage_toggle_proto.test.js` (each line's edge, the tighter budget deciding, off at the hard line, no
  reading, a stale reading with and without a last step, a reset that passed, garbage numbers, no windows).
- Sample data is shaped like the #872 slice 1 recorder (`~/.claude/logs/plan-usage.jsonl`):
  `{ five_hour: { used_pct, resets_at }, seven_day: { used_pct, resets_at }, windows: [{ start, end, peak_pct,
  hit_limit }], weekly_pace }`, with `weekly_pace` read as the week's projected used % at its reset. The recorder
  decides the real shape.
- The look is the celestial-navigation tokens (#428, the same values as `show_window.css`), fonts bundled beside the
  page (OFL, from `@fontsource`) because the mock-up window has no network.

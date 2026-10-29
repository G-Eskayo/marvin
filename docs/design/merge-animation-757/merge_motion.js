// MR Review merge motion (marvin#757): the choreography only, no DOM. Every animation is a list of named phases
// ({ name, start, end } in ms), so the prototype page plays them, the recorder seeks them frame by frame, and the tests
// check the order. Round 2 follows the owner's answers on PR #761: everything stays in place and moves left to right
// (out of Open, into Merged, new MRs coming in), a solid fill with a closing sweep a third of a card behind it, the
// gap closes only once that sweep is done, about 1.3x slower, one at a time in the order GitHub confirms them.
// A classic script, not a module, so the prototype opens straight from Finder (file://). It sets globalThis.MergeMotion.
;(function (root) {
  'use strict'

  // The website's blue: the brand blue (gileskayo.me brand.css --blue) with the live site's focus-glow halo
  // (main.css: 0 0 8px rgba(102, 175, 233, .6)).
  const BLUE = { core: '#198fd9', halo: 'rgba(102, 175, 233, 0.6)' }

  // Round 1's timings, which the owner asked to slow to about 1.3x.
  const SPEED = 1.3
  const BASE = {
    sweep: 560, // the fill crosses the card (and the closing sweep, at the same speed, a third behind)
    close: 380, // the cards below fall together
    gapOpen: 320, // a space opens where the card belongs
    splitPause: 220, // split view: between leaving Open and the space opening in Merged
    fade: 220 // Reduce Motion: the card fades out or in
  }
  const TIMING = Object.fromEntries(Object.entries(BASE).map(([k, v]) => [k, Math.round(v * SPEED)]))
  // Reduce Motion's short move, as the owner chose it: 0.2 s, not slowed.
  const REDUCED_MOVE = 200
  // The closing sweep follows the fill by a third of the card.
  const LAG = 1 / 3

  const at = (name, start, duration, extra) => Object.assign({ name, start, end: start + duration }, extra)
  const totalOf = (phases) => (phases.length ? Math.max(...phases.map((p) => p.end)) : 0)
  const shift = (phases, by) => phases.map((p) => Object.assign({}, p, { start: p.start + by, end: p.end + by }))
  const tag = (phases, extra) => phases.map((p) => Object.assign({}, p, extra))

  // Leaving, in place: the fill's leading edge crosses the card; the closing sweep follows a third of a card behind
  // and leaves the space empty; once it is done, the cards below fall together.
  function leave(reduced) {
    if (reduced) return [at('fade', 0, TIMING.fade), at('close', TIMING.fade, REDUCED_MOVE)]
    const S = TIMING.sweep, lag = Math.round(S * LAG)
    return [at('fill', 0, S), at('clear', lag, S), at('close', lag + S, TIMING.close)]
  }

  // Coming in: the space opens where the card belongs; the fill sweeps across it and the card shows behind the fill,
  // a third of a card back. The mirror of leave().
  function enter(reduced) {
    if (reduced) return [at('gapOpen', 0, REDUCED_MOVE), at('fadeIn', REDUCED_MOVE, TIMING.fade)]
    const G = TIMING.gapOpen, S = TIMING.sweep, lag = Math.round(S * LAG)
    return [at('gapOpen', 0, G), at('fill', G, S), at('reveal', G + lag, S)]
  }

  function planEnter({ reduced = false } = {}) {
    const phases = enter(reduced)
    return { direction: 'ltr', phases, total: totalOf(phases) }
  }

  // Arriving in Merged: the same motion, from the left, on its own tab and in the split view alike.
  const planArrival = ({ reduced = false } = {}) => planEnter({ reduced })

  // Leaving Open. Split view: then, a moment later, the Merged column opens a space and the card comes in from the
  // left, so the whole trip reads as one path left to right.
  function planMerge({ layout = 'list', reduced = false } = {}) {
    const out = tag(leave(reduced), { column: 'open' })
    let phases = out
    if (layout === 'split') {
      const gone = reduced ? out[0].end : out.find((p) => p.name === 'clear').end
      phases = out.concat(tag(shift(enter(reduced), gone + (reduced ? 0 : TIMING.splitPause)), { column: 'merged' }))
    }
    return { direction: 'ltr', phases, total: totalOf(phases) }
  }

  // Where a card coming in belongs: after every item that sorts before it or level with it, so it never jumps ahead
  // of one already there. O(n) time, O(1) space.
  function placeOf(items, item, compare) {
    let i = 0
    while (i < items.length && compare(items[i], item) <= 0) i++
    return i
  }

  // Several merges: one at a time, each in full with its gap closed before the next, in the order GitHub confirmed
  // them (`at`, ms), not the order of the list. One confirmed after the last has finished starts when it's confirmed.
  // O(n log n) time for the sort, O(n) space.
  function planQueue(events, { layout = 'list', reduced = false } = {}) {
    if (!events.length) return { cards: [], phases: [], total: 0 }
    const one = planMerge({ layout, reduced })
    const order = events.map((e, i) => ({ e, i })).sort((a, b) => a.e.at - b.e.at || a.i - b.i).map((x) => x.e)
    const cards = []
    let free = 0
    for (const e of order) {
      const offset = Math.max(e.at, free)
      cards.push({ key: e.key, offset })
      free = offset + one.total
    }
    const phases = cards.flatMap((c) => tag(shift(one.phases, c.offset), { key: c.key }))
    return { cards, phases, total: totalOf(phases) }
  }

  // Nothing plays until GitHub confirms the merge, so a card never has to come back. Approve puts the card in
  // `waiting` (it shows its usual merge progress); GitHub's answer either plays it or leaves it where it always was.
  const initialGate = () => ({ waiting: [], done: [] })
  function onMergeEvent(state, { type, key }) {
    const waiting = state.waiting.filter((k) => k !== key)
    if (type === 'approved') return { state: Object.assign({}, state, { waiting: waiting.concat(key) }), play: [] }
    if (type === 'refused') return { state: Object.assign({}, state, { waiting }), play: [], refused: key }
    if (type === 'confirmed') {
      if (state.done.includes(key)) return { state: Object.assign({}, state, { waiting }), play: [] }
      return { state: Object.assign({}, state, { waiting, done: state.done.concat(key) }), play: [key] }
    }
    return { state, play: [] }
  }

  // A confirmed merge. The list on screen plays it now; otherwise it waits (once) for the list to be shown again.
  function routeMerge(state, key) {
    if (state.listVisible) return { state, play: [key] }
    const pending = state.pending.includes(key) ? state.pending : state.pending.concat(key)
    return { state: Object.assign({}, state, { pending }), play: [] }
  }

  // The list is shown again (back from an MR, back to the tab, the dashboard woke). Merges you missed just show
  // the result, with a count. `focus` is the MR you were inside: it still plays its leave on the way back.
  function onListShown(state, { focus = null } = {}) {
    const pending = state.pending || []
    const next = Object.assign({}, state, { listVisible: true, pending: [] })
    const play = pending.includes(focus) ? [focus] : []
    const settled = pending.filter((k) => k !== focus)
    return { state: next, play, settled, note: settled.length ? `${settled.length} merged while you were away` : null }
  }

  // Where the change is relative to what you're looking at. Off screen it happens without playing; above you, the
  // page shifts by the card's height (up for one leaving, down for one coming in) so your place holds.
  function scrollPlan({ top, height, gap, scrollTop, viewport, change = 'leave' }) {
    if (top + height <= scrollTop) return { where: 'above', play: false, scrollDelta: (change === 'enter' ? 1 : -1) * (height + gap) }
    if (top >= scrollTop + viewport) return { where: 'below', play: false, scrollDelta: 0 }
    return { where: 'in', play: true, scrollDelta: 0 }
  }

  // A swipe (#756) lands mid-plan: the animation jumps to its end and the swipe goes now.
  const interrupt = (plan) => ({ seekTo: plan.total, navigateIn: 0 })

  root.MergeMotion = { BLUE, SPEED, BASE, TIMING, LAG, planMerge, planEnter, planArrival, placeOf, planQueue, initialGate, onMergeEvent, routeMerge, onListShown, scrollPlan, interrupt }
})(typeof globalThis !== 'undefined' ? globalThis : window)

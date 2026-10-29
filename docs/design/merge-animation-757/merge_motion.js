// MR Review merge motion (marvin#757): the choreography only, no DOM. Every animation is a list of named phases
// ({ name, start, end } in ms), so the prototype page plays them, the recorder seeks them frame by frame, and the tests
// check the order (gap closes only after the card has gone, Reduce Motion never moves anything).
// A classic script, not a module, so the prototype opens straight from Finder (file://). It sets globalThis.MergeMotion.
;(function (root) {
  'use strict'

  // The website's blue: the brand blue (gileskayo.me brand.css --blue) with the live site's focus-glow halo
  // (main.css: 0 0 8px rgba(102, 175, 233, .6)). Amber is the dashboard's "GitHub disagreed" tone.
  const BLUE = { core: '#198fd9', halo: 'rgba(102, 175, 233, 0.6)' }
  const AMBER = '#f59e0b'

  const TIMING = {
    sweep: 560, // the blue band crosses the card
    follow: 220, // the card starts after the band, so it reads as following it
    slide: 460, // the card leaves
    trail: 760, // the light trail fades out after it
    close: 380, // the cards below move up
    gapOpen: 320, // a space opens at the top of Merged
    arrive: 460, // the card slides into it
    splitPause: 220, // "a moment later": between leaving Open and the space opening in Merged
    cascade: 160, // stagger between cards merged together
    fade: 220, // Reduce Motion: the card fades out
    settle: 200 // Reduce Motion: the cards below dissolve into their new places
  }

  // Missed merges (inside an MR, a tab away, the dashboard asleep) replay on return only while it's recent and few.
  const AWAY = { maxAwayMs: 10 * 60 * 1000, maxReplay: 3 }

  const at = (name, start, duration, extra) => Object.assign({ name, start, end: start + duration }, extra)
  const totalOf = (phases) => (phases.length ? Math.max(...phases.map((p) => p.end)) : 0)
  const shift = (phases, by) => phases.map((p) => Object.assign({}, p, { start: p.start + by, end: p.end + by }))

  function leave(reduced) {
    if (reduced) return [at('fade', 0, TIMING.fade), at('settle', TIMING.fade, TIMING.settle)]
    const T = TIMING
    const slide = at('slide', T.follow, T.slide)
    // The gap starts closing as the card's last fifth leaves, so the list never sits with a hole in it, and nothing
    // slides under a card that is still on screen.
    const closeAt = slide.start + Math.round(0.8 * T.slide)
    return [at('sweep', 0, T.sweep), slide, at('trail', T.follow, T.trail), at('close', closeAt, T.close)]
  }

  function arrival(reduced) {
    if (reduced) return [at('fadeIn', 0, TIMING.fade)]
    const T = TIMING
    return [at('gapOpen', 0, T.gapOpen), at('arrive', T.gapOpen, T.arrive), at('sweep', T.gapOpen, T.sweep, { reverse: true })]
  }

  // Arriving in Merged. On its own tab it slides in from the right; in the split view it carries on from the side it
  // left Open (the left edge of the Merged column) unless the owner picks the right.
  function planArrival({ layout = 'list', reduced = false, splitEntry = 'left' } = {}) {
    const phases = arrival(reduced)
    return { entry: layout === 'split' ? splitEntry : 'right', phases, total: totalOf(phases) }
  }

  // Leaving Open. List: out to the left. Split: out to the right, then the Merged column opens a space and takes it.
  function planMerge({ layout = 'list', reduced = false, splitEntry = 'left' } = {}) {
    const out = leave(reduced).map((p) => Object.assign(p, { column: 'open' }))
    let phases = out
    if (layout === 'split') {
      const leftAt = reduced ? out[0].end : out.find((p) => p.name === 'slide').end
      const into = shift(arrival(reduced), leftAt + (reduced ? 0 : TIMING.splitPause)).map((p) => Object.assign(p, { column: 'merged' }))
      phases = out.concat(into)
    }
    return { exit: layout === 'split' ? 'right' : 'left', entry: layout === 'split' ? splitEntry : null, phases, total: totalOf(phases) }
  }

  // Several merges at once. cascade: staggered top to bottom, one gap close at the end. together: all at once.
  // sequence: each in full, gap closed, before the next. Reduce Motion: one fade for all.
  function planBatch(keys, { mode = 'cascade', layout = 'list', reduced = false } = {}) {
    if (!keys.length) return { cards: [], phases: [], total: 0 }
    if (reduced) {
      const phases = planMerge({ layout, reduced }).phases
      return { cards: keys.map((key) => ({ key, offset: 0 })), phases, total: totalOf(phases) }
    }
    const single = planMerge({ layout })
    if (mode === 'sequence') {
      const cards = keys.map((key, i) => ({ key, offset: i * single.total }))
      const phases = cards.flatMap((c) => shift(single.phases, c.offset).map((p) => Object.assign(p, { key: c.key })))
      return { cards, phases, total: totalOf(phases) }
    }
    const step = mode === 'together' ? 0 : TIMING.cascade
    const cards = keys.map((key, i) => ({ key, offset: i * step }))
    const own = single.phases.filter((p) => p.name !== 'close')
    const phases = cards.flatMap((c) => shift(own, c.offset).map((p) => Object.assign(p, { key: c.key })))
    const close = single.phases.find((p) => p.name === 'close')
    phases.push(shift([close], cards[cards.length - 1].offset)[0])
    return { cards, phases, total: totalOf(phases) }
  }

  // A merge arrives. The list on screen plays it now; otherwise it waits (once) for the list to be shown again.
  function routeMerge(state, key) {
    if (state.listVisible) return { state, play: [key] }
    const pending = state.pending.includes(key) ? state.pending : state.pending.concat(key)
    return { state: Object.assign({}, state, { pending }), play: [] }
  }

  // The list is shown again (back from an MR, back to the tab, the dashboard woke). Policies:
  // replay-recent (default): replay if away briefly and few were missed, else show the result with a count;
  // replay-all: always replay; show-result: never replay. `focus` is the MR you were inside: its slide-out always
  // plays on the way back (#757 point 2), whatever the policy and however long you read it.
  function onListShown(state, { now, policy = 'replay-recent', focus = null } = {}) {
    const pending = state.pending || []
    const next = Object.assign({}, state, { listVisible: true, pending: [], hiddenSince: null })
    if (!pending.length) return { state: next, play: [], settled: [], note: null }
    const mine = pending.includes(focus) ? [focus] : []
    const others = pending.filter((k) => k !== focus)
    const recent = now - (state.hiddenSince || 0) <= AWAY.maxAwayMs && others.length <= AWAY.maxReplay
    const replay = policy === 'replay-all' || (policy === 'replay-recent' && recent)
    if (replay || !others.length) return { state: next, play: pending, settled: [], note: null }
    return { state: next, play: mine, settled: others, note: `${others.length} merged while you were away` }
  }

  // Where the merged card is relative to what you're looking at. Off screen it leaves without playing; above you,
  // the page shifts by its height so your place holds.
  function scrollPlan({ top, height, gap, scrollTop, viewport }) {
    if (top + height <= scrollTop) return { where: 'above', play: false, scrollDelta: -(height + gap) }
    if (top >= scrollTop + viewport) return { where: 'below', play: false, scrollDelta: 0 }
    return { where: 'in', play: true, scrollDelta: 0 }
  }

  // A swipe (#756) lands t ms into a plan. finish: jump to the end now and navigate; wait: navigate when it ends.
  function interrupt(plan, t, policy = 'finish') {
    if (policy === 'wait') return { seekTo: null, navigateIn: Math.max(0, plan.total - t) }
    return { seekTo: plan.total, navigateIn: 0 }
  }

  // GitHub refused a merge the screen already showed (local-first): the card comes back the way it went, with an
  // amber pulse, next to the existing "GitHub disagreed" notice.
  function planReturn({ layout = 'list', reduced = false } = {}) {
    const entry = layout === 'split' ? 'right' : 'left'
    if (reduced) {
      const phases = [at('fadeIn', 0, TIMING.fade), at('pulse', TIMING.fade, 600, { tone: 'amber' })]
      return { entry, phases, total: totalOf(phases) }
    }
    const T = TIMING
    const phases = [at('gapReopen', 0, T.close), at('slideBack', T.close, T.slide), at('pulse', T.close + T.slide, 700, { tone: 'amber' })]
    return { entry, phases, total: totalOf(phases) }
  }

  root.MergeMotion = { BLUE, AMBER, TIMING, AWAY, planMerge, planArrival, planBatch, routeMerge, onListShown, scrollPlan, interrupt, planReturn }
})(typeof globalThis !== 'undefined' ? globalThis : window)

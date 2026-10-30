// MR Review's merge motion (marvin#838), built from the #761 mock-up's choreography (docs/design/merge-animation-757/).
// No DOM here: every animation is a list of named phases ({ name, start, end } in ms), and frame() says what a card
// looks like at any time t, so playing, seeking (a swipe finishing it at once) and the recordings all show the same
// thing. The owner's round-2 answers on PR #761 (2026-10-30) win over round 1 (2026-10-29):
//   - in place: a solid #198fd9 fill with the glow crosses the card, a closing sweep a third of a card behind, then the
//     cards close up on a Motion spring with no bounce; about 0.8x round 2's recorded pace
//   - every direction left to right: leaving Open, arriving on Merged, new MRs coming into Open, the split view as one
//     path with no pause
//   - once GitHub confirms, the merge bar morphs into a green check-mark circle, then the sweep plays
//   - nothing plays before GitHub confirms; several play one at a time in the order they were confirmed
//   - scrolled away: a chip per event, one at a time, never twice; your place never moves
// The light bar on the sweep's edge (round 1's look, which the owner asked back) is CSS only (index.css .mm-band).
import * as MotionModule from '../vendor/motion-14.8.0.js'

// The vendored Motion build is UMD: a CommonJS module under the tests, a global (window.Motion) in the app's build.
const Motion = MotionModule.spring ? MotionModule : MotionModule.default?.spring ? MotionModule.default : globalThis.Motion

// The website's blue: the brand blue (gileskayo.me brand.css --blue) with the live site's focus-glow halo.
export const BLUE = { core: '#198fd9', halo: 'rgba(102, 175, 233, 0.6)' }

// Round 1's timings; round 2 slowed them 1.3x, and the owner then asked for about 0.8x of that.
export const SPEED = 1.3 * 0.8
export const BASE = {
  sweep: 560, // the fill crosses the card (and the closing sweep, at the same speed, a third behind)
  close: 380, // the cards below fall together
  gapOpen: 320, // a space opens where the card belongs
  fade: 220 // Reduce Motion: the card fades out or in
}
export const TIMING = Object.fromEntries(Object.entries(BASE).map(([k, v]) => [k, Math.round(v * SPEED)]))
// Reduce Motion's short move, as the owner chose it: 0.2 s, whatever the pace.
export const REDUCED_MOVE = 200
// The closing sweep follows the fill by a third of the card.
export const LAG = 1 / 3
// The check mark once GitHub confirms (round 2 note on "waiting"): the bar shrinks into a green circle, the tick draws,
// and it holds a moment so it reads as done before the sweep. Under Reduce Motion the check fades in instead.
export const CONFIRM = { morph: 320, tick: 240, hold: 200 }
// A chip ("↑ #741 merged above you") shows this long, the time the mock-up showed it.
export const CHIP_MS = 2000
// How many played motions and confirmed merges are remembered (so a late duplicate never plays twice). Bounded.
export const MOTION_MEMORY = 200

const LAYOUTS = new Set(['list', 'split'])
const checkLayout = (fn, layout) => {
  if (!LAYOUTS.has(layout)) throw new Error(`${fn}: unknown layout "${layout}"`)
}
const at = (name, start, duration, extra) => Object.assign({ name, start, end: start + duration }, extra)
const totalOf = (phases) => (phases.length ? Math.max(...phases.map((p) => p.end)) : 0)
const shift = (phases, by) => phases.map((p) => ({ ...p, start: p.start + by, end: p.end + by }))
const tag = (phases, extra) => phases.map((p) => ({ ...p, ...extra }))
const remember = (list, item) => [...list.filter((x) => x !== item), item].slice(-MOTION_MEMORY)

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

export function planConfirm({ reduced = false } = {}) {
  const phases = reduced
    ? [at('checkFade', 0, REDUCED_MOVE), at('hold', REDUCED_MOVE, CONFIRM.hold)]
    : [at('morph', 0, CONFIRM.morph), at('tick', CONFIRM.morph, CONFIRM.tick), at('hold', CONFIRM.morph + CONFIRM.tick, CONFIRM.hold)]
  return { phases, total: totalOf(phases) }
}

export function planEnter({ reduced = false } = {}) {
  const phases = enter(reduced)
  return { direction: 'ltr', phases, total: totalOf(phases) }
}

// Arriving in Merged: the same motion, left to right on its own tab and in the split view alike (round 2).
export function planArrival({ layout = 'list', reduced = false } = {}) {
  checkLayout('planArrival', layout)
  return planEnter({ reduced })
}

// Leaving Open. `confirm`: the card showed merge progress, so its bar first turns into the check mark. Split view: the
// Merged column opens its space the moment the card has gone from Open, so the trip is one path with no pause.
export function planMerge({ layout = 'list', reduced = false, confirm = false } = {}) {
  checkLayout('planMerge', layout)
  const pre = confirm ? planConfirm({ reduced }) : { phases: [], total: 0 }
  const out = tag(shift(leave(reduced), pre.total), { column: 'open' })
  let phases = tag(pre.phases, { column: 'open' }).concat(out)
  if (layout === 'split') {
    const gone = out.find((p) => p.name === (reduced ? 'fade' : 'clear')).end
    phases = phases.concat(tag(shift(enter(reduced), gone), { column: 'merged' }))
  }
  return { direction: 'ltr', phases, total: totalOf(phases) }
}

// Where a card coming in belongs: after every item that sorts before it or level with it. O(n) time, O(1) space.
export function placeOf(items, item, compare) {
  let i = 0
  while (i < items.length && compare(items[i], item) <= 0) i++
  return i
}

// Several merges planned ahead: one at a time, each in full with its gap closed before the next, in the order GitHub
// confirmed them (`at`, ms). O(n log n) time for the sort, O(n) space.
export function planQueue(events, opts = {}) {
  if (!events.length) return { cards: [], phases: [], total: 0 }
  const one = planMerge(opts)
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

// The live queue the dashboard plays from: motions ({kind: 'leave' | 'enter', key}) in the order they were triggered,
// one playing at a time. A motion queued, playing or already played is never added again. O(n) per add (n <= the
// queue plus MOTION_MEMORY), O(MOTION_MEMORY) space.
const idOf = (m) => `${m.kind}:${m.key}`
export const initialMotions = () => ({ playing: null, queue: [], played: [] })
export function addMotion(state, item) {
  const id = idOf(item)
  if ((state.playing && idOf(state.playing) === id) || state.queue.some((m) => idOf(m) === id) || state.played.includes(id)) return state
  return { ...state, queue: state.queue.concat({ kind: item.kind, key: item.key }) }
}
export function nextMotion(state) {
  if (state.playing || !state.queue.length) return { state, item: null }
  const [item, ...queue] = state.queue
  return { state: { ...state, playing: item, queue }, item }
}
export function motionDone(state) {
  if (!state.playing) return state
  return { ...state, playing: null, played: remember(state.played, idOf(state.playing)) }
}
// Leaving the list (a swipe, opening an MR, another tab): the one playing has already been finished at once by the
// caller; whatever was waiting is handed back to settle without playing (the result, not the motion).
export function flushMotions(state) {
  const done = motionDone(state)
  const settled = (state.playing ? [state.playing] : []).concat(state.queue)
  return { state: { ...done, queue: [], played: settled.reduce((p, m) => remember(p, idOf(m)), done.played) }, settled }
}

// Chips when scrolled away: one shows at a time, the rest wait their turn in the order they came; an event (kind + MR)
// is shown once, ever. O(n) per add, O(MOTION_MEMORY) space.
const chipId = (c) => `${c.kind}:${c.key}`
export const initialChips = () => ({ current: null, queue: [], seen: [] })
export function addChip(state, chip) {
  const id = chipId(chip)
  if (state.seen.includes(id)) return state
  const seen = remember(state.seen, id)
  if (!state.current) return { ...state, current: chip, seen }
  return { ...state, queue: state.queue.concat(chip), seen }
}
export function chipDone(state) {
  if (!state.current) return state
  const [current = null, ...queue] = state.queue
  return { ...state, current, queue }
}
export const chipText = (chip) => `↑ #${chip.number} ${chip.kind === 'came-in' ? 'came in' : 'merged'} above you`

// Nothing plays until GitHub confirms the merge, so a card never has to come back. Approve puts the card in `waiting`
// (it shows its merge progress and a blue border); GitHub's answer either plays it or leaves it where it always was.
export const initialGate = () => ({ waiting: [], done: [] })
export function onMergeEvent(state, { type, key }) {
  const waiting = state.waiting.filter((k) => k !== key)
  if (type === 'approved') return { state: { ...state, waiting: waiting.concat(key) }, play: [] }
  if (type === 'refused') return { state: { ...state, waiting }, play: [], refused: key }
  if (type === 'confirmed') {
    if (state.done.includes(key)) return { state: { ...state, waiting }, play: [] }
    return { state: { ...state, waiting, done: remember(state.done, key) }, play: [key] }
  }
  return { state, play: [] }
}
// The op the main process pushes (mr:mergeEvent, merge_ops.js) as a gate event: merging is waiting for GitHub, merged
// is GitHub's confirmation, anything else ends the wait without playing.
export function gateEventOf(op) {
  if (!op || !op.state) return null
  if (op.state === 'merging') return 'approved'
  if (op.state === 'merged') return 'confirmed'
  return 'refused'
}

// A confirmed merge. The list on screen plays it now; otherwise it waits (once) for the list to be shown again.
export function routeMerge(state, key) {
  if (state.listVisible) return { state, play: [key] }
  const pending = state.pending.includes(key) ? state.pending : state.pending.concat(key)
  return { state: { ...state, pending }, play: [] }
}

// The list is shown again (back from an MR, back to the tab, the dashboard woke). Merges you missed just show the
// result, with a count. `focus` is the MR you were inside: it still plays its leave on the way back.
export function onListShown(state, { focus = null } = {}) {
  const pending = state.pending || []
  const next = { ...state, listVisible: true, pending: [] }
  const play = pending.includes(focus) ? [focus] : []
  const settled = pending.filter((k) => k !== focus)
  return { state: next, play, settled, note: settled.length ? `${settled.length} merged while you were away` : null }
}

// Where the change is relative to what you're looking at. Off screen it happens without playing; above you, the page
// shifts by the card's height (up for one leaving, down for one coming in) so your place holds.
export function scrollPlan({ top, height, gap, scrollTop, viewport, change = 'leave' }) {
  if (top + height <= scrollTop) return { where: 'above', play: false, scrollDelta: (change === 'enter' ? 1 : -1) * (height + gap) }
  if (top >= scrollTop + viewport) return { where: 'below', play: false, scrollDelta: 0 }
  return { where: 'in', play: true, scrollDelta: 0 }
}

// A swipe (#756) lands mid-plan: the animation jumps to its end and the swipe goes now.
export const interrupt = (plan) => ({ seekTo: plan.total, navigateIn: 0 })

// The list on screen: GitHub's list (`next`), plus the cards in `keep` that GitHub has dropped but are still sweeping
// out, each where it was (after the card that was before it). The kept card is its last shown version. O(n·k) time
// for k kept cards, O(n) space.
export function mergeShown(prev, next, keep) {
  const out = next.slice()
  const inNext = new Set(next.map((x) => x.key))
  prev.forEach((item, i) => {
    if (inNext.has(item.key) || !keep.has(item.key)) return
    let j = i - 1
    while (j >= 0 && !out.some((x) => x.key === prev[j].key)) j--
    const at = j < 0 ? 0 : out.findIndex((x) => x.key === prev[j].key) + 1
    out.splice(at, 0, item)
  })
  return out
}

// "reverted by #N" on a Merged row: a later merged PR in the same repo titled the way GitHub titles a revert
// (Revert "<original title>"), or a revert naming the PR by number (Revert #741 …). O(n) time and space.
const REVERT_TITLE = /^Revert "(.+)"$/
const REVERT_NUMBER = /^Revert(?:s)?\b[^#]*#(\d+)\b/i
export function revertedBy(rows) {
  const merged = (rows || []).filter((r) => r.kind === 'merged')
  const byTitle = new Map(merged.map((r) => [`${r.repo}\u0000${r.title}`, r]))
  const byNumber = new Map(merged.map((r) => [`${r.repo}#${r.number}`, r]))
  const out = {}
  for (const r of merged) {
    const t = REVERT_TITLE.exec(r.title || ''), n = REVERT_NUMBER.exec(r.title || '')
    const original = t ? byTitle.get(`${r.repo}\u0000${t[1]}`) : n ? byNumber.get(`${r.repo}#${n[1]}`) : null
    if (original && original.url !== r.url) out[original.url] = r.number
  }
  return out
}

// ---------- frame: what a card looks like at time t ----------
// The gap opens and closes on a Motion spring with no bounce; the sweep uses Motion's easeInOut. A spring sampled at a
// fixed time is a pure function of that time, so frame() stays pure.
const SPRING = Motion.spring({ keyframes: [0, 1], visualDuration: 1, bounce: 0 })
const SPRING_END = SPRING.next(1000).value
const springEase = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : SPRING.next(x * 1000).value / SPRING_END)
const sweepEase = Motion.easeInOut
const clamp = (x) => Math.max(0, Math.min(1, x))
const find = (phases, name) => phases.find((p) => p.name === name)
const prog = (ph, t) => (ph ? clamp((t - ph.start) / Math.max(1, ph.end - ph.start)) : 0)

// The band's two edges (percent of the card): one eased trip from the fill's start to the trailing sweep's end, so the
// band stays a third of the card wide all the way across instead of stretching where the two would ease apart.
function edges(lead, trail, t) {
  const p = prog({ start: lead.start, end: trail.end }, t)
  if (p >= 1) return [100, 100] // exactly, not 99.99…: no sliver of card left behind
  const w = 100 * LAG, x = (100 + w) * sweepEase(p)
  return [Math.max(0, x - w), Math.min(100, x)]
}

// { lo, hi }: the part of the card showing (percent of its width); band: { lo, hi } of the solid blue, or null;
// height: the slot's share of its full height; opacity; border: the brand-blue border; check: the bar-to-check morph.
export function frame(phases, t) {
  const out = { lo: 0, hi: 100, band: null, height: 1, opacity: 1, border: false, check: null }
  const morph = find(phases, 'morph'), tick = find(phases, 'tick'), checkFade = find(phases, 'checkFade')
  if (morph) out.check = { opacity: 1, morph: sweepEase(prog(morph, t)), tick: prog(tick, t) }
  else if (checkFade) out.check = { opacity: prog(checkFade, t), morph: 1, tick: 1 }
  const fade = find(phases, 'fade'), fadeIn = find(phases, 'fadeIn'), gapOpen = find(phases, 'gapOpen'), close = find(phases, 'close')
  const fill = find(phases, 'fill'), clear = find(phases, 'clear'), reveal = find(phases, 'reveal')
  if (gapOpen) out.height = springEase(prog(gapOpen, t))
  if (close) out.height = 1 - springEase(prog(close, t))
  if (fade) out.opacity = 1 - prog(fade, t)
  if (fadeIn) out.opacity = prog(fadeIn, t)
  if (fill && clear) {
    const [c, f] = edges(fill, clear, t)
    out.lo = c
    if (f - c > 0.05) out.band = { lo: c, hi: f }
    out.border = f > 0 && c < 100
  } else if (fill && reveal) {
    const [r, f] = edges(fill, reveal, t)
    out.hi = t >= reveal.end ? 100 : f
    if (f - r > 0.05 && t < reveal.end) out.band = { lo: r, hi: f }
    out.border = f > 0 && r < 100 && t < reveal.end
  }
  return out
}

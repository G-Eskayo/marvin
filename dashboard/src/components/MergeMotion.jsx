import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  BLUE, CHIP_MS, planMerge, planEnter, frame, scrollPlan, interrupt, mergeShown,
  initialMotions, addMotion, nextMotion, motionDone, flushMotions, initialChips, addChip, chipDone, chipText, animate
} from '../lib/merge_motion.js'
import { mergeWatch } from '../lib/merge_watch.js'

// The merge motion in the real lists (marvin#838; the choreography and its tests are lib/merge_motion.js, approved
// as the #761 mock-up). A list renders `shown` (GitHub's items, plus cards still sweeping out) and wraps each item in
// <MotionSlot>. Leaving and arriving cards play one at a time, in the order they were triggered: a merge when GitHub
// confirms it (mergeWatch), an arrival when a new item shows up in the list. Each frame comes from frame(phases, t),
// driven by Motion's animate() over t, so finishing at once (a swipe, leaving the list) is just the last frame.
// Off screen, a change happens without playing: above you the page shifts by exactly the card, so your place holds,
// and a chip says what happened.
const PAD = 16 // the space under each card (the list's gap), part of the slot so it closes with it
const GREEN = '#34d399' // the merge bar's own "done" green (CheckProgress ready tone, emerald-400)

const reducedMotion = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

function scrollParent(el) {
  for (let p = el?.parentElement; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY
    if ((o === 'auto' || o === 'scroll') && p.scrollHeight > p.clientHeight) return p
  }
  return document.scrollingElement
}

// Where the slot sits in its scroll box, for scrollPlan.
function placeIn(el, scroller) {
  const box = scroller.getBoundingClientRect(), r = el.getBoundingClientRect()
  return { top: r.top - box.top + scroller.scrollTop, scrollTop: scroller.scrollTop, viewport: scroller.clientHeight }
}

// The check mark drawn over the merge bar: a green pill the bar's size that becomes a circle, then the tick draws.
function makeCheck(body, bar) {
  const b = body.getBoundingClientRect(), r = bar.getBoundingClientRect()
  const el = document.createElement('div')
  el.setAttribute('data-motion-check', '')
  el.setAttribute('aria-hidden', 'true')
  el.className = 'mm-check'
  el.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6.5 12.5l3.6 3.6 7.4-8.2" pathLength="1"/></svg>'
  body.appendChild(el)
  return { el, bar, box: { left: r.left - b.left, top: r.top - b.top, width: r.width, height: Math.max(2, r.height) } }
}
const D = 22 // the circle's diameter
function drawCheck(check, c) {
  const { el, bar, box } = check
  const w = box.width + (D - box.width) * c.morph, h = box.height + (D - box.height) * c.morph
  Object.assign(el.style, {
    left: `${box.left + (box.width - w) / 2}px`, top: `${box.top + (box.height - h) / 2}px`, width: `${w}px`, height: `${h}px`,
    borderRadius: `${Math.min(w, h) / 2}px`, opacity: String(c.opacity), background: GREEN
  })
  el.style.setProperty('--mm-tick', String(1 - c.tick))
  bar.style.opacity = c.morph > 0 || c.opacity > 0 ? '0' : ''
}

function apply(slot, parts, f, full) {
  const { body, card, band, check } = parts
  slot.style.height = `${f.height * full}px`
  body.style.opacity = f.opacity === 1 ? '' : String(f.opacity)
  body.style.clipPath = f.lo <= 0 && f.hi >= 100 ? '' : `inset(0 ${100 - f.hi}% ${PAD}px ${f.lo}% round 8px)`
  if (band) {
    band.style.opacity = f.band ? '1' : '0'
    if (f.band) { band.style.left = `${f.band.lo}%`; band.style.width = `${f.band.hi - f.band.lo}%` }
  }
  if (card) card.style.borderColor = f.border || f.check ? BLUE.core : ''
  if (check && f.check) drawCheck(check, f.check)
}

// options.chips: say "↑ #N … above you" for changes out of view (the Open list); the Merged list doesn't.
// `items` null = not loaded yet. The first list is taken as it is, and so is every list while `animateChanges` is
// false (the Merged view until its first fresh read: what merged while you were away is a result, not a motion).
export function useMergeMotion(items, { keyOf = (x) => x.url, numberOf = (x) => x.number, visible = true, focus = null, chips = true, watch = false, onRefused = null, animateChanges = true } = {}) {
  const [shown, setShown] = useState(items || [])
  const [entering, setEntering] = useState(() => new Set())
  const [chip, setChip] = useState(null)
  const [note, setNote] = useState(null)
  const [, setTick] = useState(0)
  const slots = useRef(new Map())
  const gone = useRef(new Set()) // swept out (or settled) here; hidden even if GitHub still lists it for a moment
  const keep = useRef(new Set()) // dropped by GitHub but still to sweep out
  const motions = useRef(initialMotions())
  const chipsRef = useRef(initialChips())
  const current = useRef(null)
  const scrollFix = useRef(0)
  const scroller = useRef(null)
  const prevItems = useRef(null)
  const shownRef = useRef(shown)
  shownRef.current = shown
  const visibleRef = useRef(visible)
  visibleRef.current = visible

  const byKey = (k) => shownRef.current.find((x) => keyOf(x) === k)
  const showChip = useCallback((c) => {
    if (!chips) return
    chipsRef.current = addChip(chipsRef.current, c)
    setChip(chipsRef.current.current)
  }, [chips])
  const nextChip = useCallback(() => {
    chipsRef.current = chipDone(chipsRef.current)
    setChip(chipsRef.current.current)
  }, [])

  const land = useCallback((m) => {
    if (m.kind === 'leave') { gone.current.add(m.key); keep.current.delete(m.key) }
    setEntering((s) => { if (!s.has(m.key)) return s; const n = new Set(s); n.delete(m.key); return n })
    setShown((s) => s.filter((x) => !gone.current.has(keyOf(x))))
  }, [keyOf])

  const pump = useCallback(() => {
    if (!visibleRef.current) return
    const r = nextMotion(motions.current)
    motions.current = r.state
    const m = r.item
    if (!m) return
    const done = () => { current.current = null; motions.current = motionDone(motions.current); land(m); pump() }
    const slot = slots.current.get(m.key)
    if (!slot || (m.kind === 'leave' && gone.current.has(m.key))) { done(); return }
    const box = scroller.current || (scroller.current = scrollParent(slot))
    const body = slot.firstElementChild
    const full = m.kind === 'leave' ? slot.offsetHeight : body.offsetHeight
    const where = scrollPlan({ ...placeIn(slot, box), height: full, gap: 0, change: m.kind === 'leave' ? 'leave' : 'enter' })
    const item = byKey(m.key)
    if (!where.play) {
      scrollFix.current += where.scrollDelta
      if (where.where === 'above' && item) showChip({ kind: m.kind === 'leave' ? 'merged' : 'came-in', key: m.key, number: numberOf(item) })
      done()
      return
    }
    const reduced = reducedMotion()
    const bar = m.kind === 'leave' ? slot.querySelector('[data-progress-bar]') : null
    const plan = m.kind === 'leave' ? planMerge({ reduced, confirm: !!bar }) : planEnter({ reduced })
    const parts = { body, card: body.firstElementChild, band: body.querySelector('[data-motion-band]'), check: bar ? makeCheck(body, bar) : null }
    const draw = (t) => apply(slot, parts, frame(plan.phases, t), full)
    draw(0)
    const finish = () => {
      if (current.current?.slot !== slot) return
      draw(interrupt(plan).seekTo)
      parts.check?.el.remove()
      if (parts.check) parts.check.bar.style.opacity = ''
      if (m.kind === 'enter') { slot.style.height = ''; body.style.clipPath = ''; if (parts.card) parts.card.style.borderColor = '' }
      done()
    }
    const controls = animate(0, plan.total, { duration: plan.total / 1000, ease: 'linear', onUpdate: draw, onComplete: finish })
    current.current = { slot, controls, finish }
  }, [land, showChip, numberOf])

  // A swipe, opening an MR, another tab: what's playing finishes at once, and what was waiting just settles.
  const finishAll = useCallback(() => {
    const c = current.current
    if (c) { c.controls.stop(); c.finish() }
    const f = flushMotions(motions.current)
    motions.current = f.state
    for (const m of f.unplayed) land(m)
  }, [land])

  // Queued now, played after the next commit (below), so a card coming in already has its slot in the DOM.
  const enqueue = useCallback((m) => {
    motions.current = addMotion(motions.current, m)
    if (m.kind === 'leave' && !gone.current.has(m.key)) keep.current.add(m.key)
    setTick((n) => n + 1)
  }, [])
  useLayoutEffect(() => { if (!motions.current.playing && motions.current.queue.length) pump() })

  // GitHub's list changed: dropped cards still to sweep out stay where they were; new ones wait at no height for
  // their turn; anything else dropped goes (with the page held in place if it was above you).
  useLayoutEffect(() => {
    if (items == null) return
    const next = items.filter((x) => !gone.current.has(keyOf(x)))
    const prev = prevItems.current
    prevItems.current = items
    if (prev === null || !animateChanges) { setShown(mergeShown(shownRef.current, next, keep.current)); return }
    const was = new Set(shownRef.current.map(keyOf))
    const now = new Set(next.map(keyOf))
    for (const x of shownRef.current) {
      const k = keyOf(x)
      if (now.has(k) || keep.current.has(k)) continue
      if (watch && (mergeWatch.isWaiting(k) || mergeWatch.isConfirmed(k))) { keep.current.add(k); continue }
      const slot = slots.current.get(k)
      if (slot && visibleRef.current) {
        const box = scroller.current || (scroller.current = scrollParent(slot))
        const where = scrollPlan({ ...placeIn(slot, box), height: slot.offsetHeight, gap: 0 })
        scrollFix.current += where.scrollDelta
      }
    }
    const added = next.filter((x) => !was.has(keyOf(x)))
    if (added.length && visibleRef.current) setEntering((s) => new Set([...s, ...added.map(keyOf)]))
    setShown(mergeShown(shownRef.current, next, keep.current))
    if (visibleRef.current) for (const x of added) enqueue({ kind: 'enter', key: keyOf(x) })
  }, [items])

  // Instant changes above you: shift the page by exactly what changed, after the DOM has it.
  useLayoutEffect(() => {
    if (!scrollFix.current || !scroller.current) return
    scroller.current.scrollTop += scrollFix.current
    scrollFix.current = 0
  })

  // On screen or not (inside an MR, the window hidden). Coming back: the MR you were inside plays, the rest are counted.
  useEffect(() => {
    if (!watch) return undefined
    mergeWatch.attach(window.api)
    const off = mergeWatch.onChange(() => setTick((n) => n + 1))
    return off
  }, [watch])
  useEffect(() => {
    if (!watch) return undefined
    const sync = () => {
      const on = visible && document.visibilityState !== 'hidden'
      if (!on) { finishAll(); mergeWatch.hide(); return }
      const refused = (k, why) => {
        // It stays in Open; if GitHub has dropped it meanwhile (closed), it just goes.
        keep.current.delete(k)
        if (!(prevItems.current || []).some((x) => keyOf(x) === k)) { gone.current.add(k); setShown((s) => s.filter((x) => keyOf(x) !== k)) }
        onRefused?.(k, why)
      }
      const back = mergeWatch.show({ play: (k) => enqueue({ kind: 'leave', key: k }), refused }, { focus })
      for (const k of back.missed) land({ kind: 'leave', key: k })
      if (back.note) setNote(back.note)
      for (const k of back.play) enqueue({ kind: 'leave', key: k })
    }
    sync()
    document.addEventListener('visibilitychange', sync)
    return () => { document.removeEventListener('visibilitychange', sync); finishAll(); mergeWatch.hide() }
  }, [watch, visible, focus])
  useEffect(() => { if (!visible && !watch) finishAll() }, [visible])

  const slotRef = useCallback((k) => (el) => { if (el) slots.current.set(k, el); else slots.current.delete(k) }, [])
  const isBlue = (k) => mergeWatch.isWaiting(k) || keep.current.has(k) || motions.current.queue.some((m) => m.kind === 'leave' && m.key === k) || (motions.current.playing?.kind === 'leave' && motions.current.playing.key === k)
  return { shown: shown.filter((x) => !gone.current.has(keyOf(x))), entering, slotRef, chip, nextChip, note, isBlue }
}

// One item of a moving list: the slot (its height opens and closes the space), the body (what the sweep clips) with
// the blue band over the card. A slot waiting to come in has no height until its turn.
export function MotionSlot({ slotRef, waiting, pad = PAD, children }) {
  return (
    <div ref={slotRef} data-motion-slot className="relative overflow-hidden" style={waiting ? { height: 0 } : undefined}>
      <div data-motion-body className="relative" style={{ paddingBottom: pad }}>
        {children}
        <div data-motion-band aria-hidden="true" className="mm-band" style={{ bottom: pad }} />
      </div>
    </div>
  )
}

// "↑ #741 merged above you": one at a time, at the top of the list's view, for CHIP_MS.
export function MotionChip({ chip, onDone }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!chip || !ref.current) return undefined
    const c = animate(ref.current, { opacity: [0, 1, 1, 0] }, { duration: CHIP_MS / 1000, times: [0, 0.08, 0.8, 1], onComplete: onDone })
    return () => c.stop()
  }, [chip])
  return (
    <div className="pointer-events-none sticky top-2 z-10 flex h-0 justify-center" aria-live="polite">
      {chip && <div ref={ref} data-motion-chip className="mm-chip rounded-full border px-3 py-1 text-xs text-neutral-100" style={{ opacity: 0 }}>{chipText(chip)}</div>}
    </div>
  )
}

// What happened while you weren't looking: just the result, with the count (the owner's round-1 answer).
export function AwayNote({ note }) {
  if (!note) return null
  return (
    <div data-motion-away className="rounded-lg border px-4 py-3 text-sm text-neutral-200" style={{ borderColor: BLUE.core }}>
      <b className="font-medium" style={{ color: BLUE.core }}>{note}</b> · see Merged
    </div>
  )
}

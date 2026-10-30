import { describe, it, expect } from 'vitest'
// MR Review's merge motion (marvin#838), built from the #761 mock-up's choreography and its tests. Round 2 of the
// owner's answers on PR #761 wins over round 1: about 0.8x round 2's pace, every direction left to right, no pause in
// the split view, a check mark once GitHub confirms, chips one at a time and never twice.
import * as M from '../src/lib/merge_motion.js'

const phase = (plan, name, extra = {}) => plan.phases.find((p) => p.name === name && Object.entries(extra).every(([k, v]) => p[k] === v))
const SWEEPS = ['fill', 'clear', 'reveal']

describe('the pace: about 0.8x the round-2 recording', () => {
  it('every timing is the round-1 timing x 1.3 (round 2) x 0.8 (the owner: faster)', () => {
    expect(M.SPEED).toBeCloseTo(1.3 * 0.8)
    for (const [k, base] of Object.entries(M.BASE)) expect(M.TIMING[k]).toBe(Math.round(base * 1.3 * 0.8))
  })

  it('a single merge in the list takes about 0.8x the recorded 1.5 s, so 1.1 to 1.3 s', () => {
    const total = M.planMerge({}).total
    expect(total).toBeGreaterThanOrEqual(1100)
    expect(total).toBeLessThanOrEqual(1300)
  })

  it('Reduce Motion keeps its 0.2 s move whatever the pace', () => {
    expect(M.REDUCED_MOVE).toBe(200)
  })
})

describe('planMerge: leaving Open, in place', () => {
  const plan = M.planMerge({ layout: 'list' })
  const fill = phase(plan, 'fill'), clear = phase(plan, 'clear'), close = phase(plan, 'close')

  it('runs left to right', () => {
    expect(plan.direction).toBe('ltr')
  })

  it('the card never moves sideways: there is no slide', () => {
    expect(phase(plan, 'slide')).toBeUndefined()
    expect(phase(plan, 'trail')).toBeUndefined()
  })

  it('a solid fill crosses the card, and the closing sweep follows it a third of a card behind', () => {
    expect(fill.start).toBe(0)
    expect(clear.start).toBe(Math.round(fill.end * M.LAG))
    expect(M.LAG).toBeCloseTo(1 / 3)
    expect(clear.end - clear.start).toBe(fill.end - fill.start)
  })

  it('the band never fills the whole card: the closing sweep starts before the fill reaches the far edge', () => {
    expect(clear.start).toBeLessThan(fill.end)
  })

  it('the cards below fall together only once the closing sweep is complete', () => {
    expect(close.start).toBe(clear.end)
    expect(plan.total).toBe(close.end)
  })

  it('every phase is on the Open column', () => {
    expect(plan.phases.every((p) => p.column === 'open')).toBe(true)
  })
})

describe('the check mark: once GitHub confirms, the bar turns into a green check, then the sweep', () => {
  const c = M.planConfirm({})
  const plan = M.planMerge({ confirm: true })

  it('the bar morphs into the circle, the tick draws, it holds a moment', () => {
    expect(c.phases.map((p) => p.name)).toEqual(['morph', 'tick', 'hold'])
    expect(phase(c, 'morph').start).toBe(0)
    expect(phase(c, 'tick').start).toBe(phase(c, 'morph').end)
    expect(phase(c, 'hold').start).toBe(phase(c, 'tick').end)
    expect(c.total).toBe(phase(c, 'hold').end)
  })

  it('the sweep starts only once the check mark is done, never over it', () => {
    expect(phase(plan, 'fill').start).toBe(c.total)
    for (const p of plan.phases.filter((x) => SWEEPS.includes(x.name) || x.name === 'close')) expect(p.start).toBeGreaterThanOrEqual(c.total)
  })

  it('it adds under a second, so a merge stays brisk', () => {
    expect(c.total).toBeGreaterThan(0)
    expect(c.total).toBeLessThan(1000)
    expect(plan.total).toBe(c.total + M.planMerge({}).total)
  })

  it('Reduce Motion: the check fades in (no morph), then the fade and the 0.2 s close', () => {
    const r = M.planMerge({ confirm: true, reduced: true })
    expect(r.phases.map((p) => p.name)).toEqual(['checkFade', 'hold', 'fade', 'close'])
    expect(phase(r, 'checkFade').end - phase(r, 'checkFade').start).toBe(200)
    expect(phase(r, 'fade').start).toBe(phase(r, 'hold').end)
  })

  it('without a bar to morph (nothing showed progress) there is no check step', () => {
    expect(M.planMerge({ confirm: false }).phases.some((p) => ['morph', 'tick', 'checkFade'].includes(p.name))).toBe(false)
  })
})

describe('planEnter: an MR coming in (to Open or to Merged)', () => {
  const plan = M.planEnter({})
  const gap = phase(plan, 'gapOpen'), fill = phase(plan, 'fill'), reveal = phase(plan, 'reveal')

  it('opens the space first, then the fill sweeps in left to right', () => {
    expect(plan.direction).toBe('ltr')
    expect(gap.start).toBe(0)
    expect(fill.start).toBe(gap.end)
  })

  it('the card shows behind the fill, a third of a card back, at the same speed', () => {
    expect(reveal.start - fill.start).toBe(Math.round((fill.end - fill.start) * M.LAG))
    expect(reveal.end - reveal.start).toBe(fill.end - fill.start)
    expect(plan.total).toBe(reveal.end)
  })

  it('arriving on the Merged tab is the same motion, left to right like everything else (round 2)', () => {
    const tab = M.planArrival({})
    expect(tab.phases).toEqual(plan.phases)
    expect(tab.direction).toBe('ltr')
    expect(M.planArrival({ layout: 'list', reduced: true }).direction).toBe('ltr')
  })

  it('in the split view it comes into Merged from the left too', () => {
    expect(M.planArrival({ layout: 'split' }).direction).toBe('ltr')
  })

  it('an unknown layout is refused rather than guessed', () => {
    expect(() => M.planArrival({ layout: 'grid' })).toThrow(/layout/)
    expect(() => M.planMerge({ layout: 'grid' })).toThrow(/layout/)
  })
})

describe('placeOf: the space opens where the MR belongs', () => {
  const byNumber = (a, b) => b.n - a.n
  const list = [{ n: 760 }, { n: 752 }, { n: 744 }, { n: 731 }]

  it('in the middle, at the top and at the bottom', () => {
    expect(M.placeOf(list, { n: 748 }, byNumber)).toBe(2)
    expect(M.placeOf(list, { n: 799 }, byNumber)).toBe(0)
    expect(M.placeOf(list, { n: 700 }, byNumber)).toBe(4)
  })

  it('into an empty list, and after equal items', () => {
    expect(M.placeOf([], { n: 1 }, byNumber)).toBe(0)
    expect(M.placeOf([{ n: 5 }, { n: 5 }], { n: 5 }, byNumber)).toBe(2)
  })
})

describe('planMerge: split view, one path with no pause (round 2)', () => {
  const plan = M.planMerge({ layout: 'split' })
  const out = plan.phases.filter((p) => p.column === 'open'), into = plan.phases.filter((p) => p.column === 'merged')

  it('leaves Open left to right and comes into Merged', () => {
    expect(plan.direction).toBe('ltr')
    expect(out.length).toBeGreaterThan(0)
    expect(into.length).toBeGreaterThan(0)
  })

  it('the space in Merged opens the moment the closing sweep finishes in Open', () => {
    const clear = out.find((p) => p.name === 'clear'), gap = into.find((p) => p.name === 'gapOpen')
    expect(gap.start).toBe(clear.end)
    expect(M.TIMING.splitPause).toBeUndefined()
  })

  it('under Reduce Motion it fades into Merged as soon as it has faded out of Open', () => {
    const r = M.planMerge({ layout: 'split', reduced: true })
    expect(phase(r, 'gapOpen', { column: 'merged' }).start).toBe(phase(r, 'fade', { column: 'open' }).end)
  })
})

describe('Reduce Motion: fade, then a short 0.2 s close', () => {
  for (const layout of ['list', 'split']) {
    it(`no sweep in the ${layout} layout; the gap closes in 0.2 s after the fade`, () => {
      const plan = M.planMerge({ layout, reduced: true })
      expect(plan.phases.filter((p) => SWEEPS.includes(p.name))).toEqual([])
      const fade = phase(plan, 'fade'), close = phase(plan, 'close')
      expect(close.start).toBe(fade.end)
      expect(close.end - close.start).toBe(200)
    })
  }

  it('coming in: the space opens in 0.2 s, then the card fades in', () => {
    const plan = M.planEnter({ reduced: true })
    expect(plan.phases.map((p) => p.name)).toEqual(['gapOpen', 'fadeIn'])
    expect(phase(plan, 'gapOpen').end).toBe(200)
  })
})

describe('planQueue: several merges, one at a time, in the order GitHub confirms them', () => {
  const one = M.planMerge({}).total

  it('plays in confirmation order, not list order', () => {
    expect(M.planQueue([{ key: 'a', at: 900 }, { key: 'b', at: 0 }, { key: 'c', at: 300 }]).cards.map((c) => c.key)).toEqual(['b', 'c', 'a'])
  })

  it('each plays in full, gap closed, before the next starts', () => {
    const plan = M.planQueue([{ key: 'a', at: 0 }, { key: 'b', at: 10 }, { key: 'c', at: 20 }])
    expect(plan.cards.map((c) => c.offset)).toEqual([0, one, 2 * one])
  })

  it('with the check step, each card has its own check before its own sweep', () => {
    const plan = M.planQueue([{ key: 'a', at: 0 }, { key: 'b', at: 0 }], { confirm: true })
    const each = M.planMerge({ confirm: true }).total
    expect(plan.cards.map((c) => c.offset)).toEqual([0, each])
    expect(phase(plan, 'morph', { key: 'b' }).start).toBeGreaterThanOrEqual(phase(plan, 'close', { key: 'a' }).end)
  })

  it('one confirmed after the last has finished starts when it is confirmed', () => {
    expect(M.planQueue([{ key: 'a', at: 0 }, { key: 'b', at: one + 5000 }]).cards[1].offset).toBe(one + 5000)
  })

  it('ties keep the order they came in, and the events are not changed', () => {
    const events = [{ key: 'x', at: 0 }, { key: 'y', at: 0 }]
    expect(M.planQueue(events).cards.map((c) => c.key)).toEqual(['x', 'y'])
    expect(events.map((e) => e.key)).toEqual(['x', 'y'])
    expect(M.planQueue([]).total).toBe(0)
  })
})

describe('the live queue: merges and arrivals play one at a time, in the order they were triggered', () => {
  const add = (s, ...items) => items.reduce((acc, it) => M.addMotion(acc, it), s)

  it('the first one plays; the next waits until it is done', () => {
    const s = add(M.initialMotions(), { kind: 'leave', key: 'b' }, { kind: 'leave', key: 'a' })
    let r = M.nextMotion(s)
    expect(r.item).toEqual({ kind: 'leave', key: 'b' })
    expect(M.nextMotion(r.state).item).toBeNull() // still playing b
    r = M.nextMotion(M.motionDone(r.state))
    expect(r.item).toEqual({ kind: 'leave', key: 'a' })
  })

  it('the same merge triggered twice (the click and the push) plays once', () => {
    let s = add(M.initialMotions(), { kind: 'leave', key: 'a' }, { kind: 'leave', key: 'a' })
    const r = M.nextMotion(s)
    s = M.addMotion(r.state, { kind: 'leave', key: 'a' }) // again while it plays
    expect(M.nextMotion(M.motionDone(s)).item).toBeNull()
  })

  it('one that already played never plays again', () => {
    const r = M.nextMotion(M.addMotion(M.initialMotions(), { kind: 'leave', key: 'a' }))
    const s = M.addMotion(M.motionDone(r.state), { kind: 'leave', key: 'a' })
    expect(M.nextMotion(s).item).toBeNull()
  })

  it('a leave and an arrival of the same MR are different motions', () => {
    const s = add(M.initialMotions(), { kind: 'enter', key: 'a' }, { kind: 'leave', key: 'a' })
    const r1 = M.nextMotion(s)
    expect(M.nextMotion(M.motionDone(r1.state)).item).toEqual({ kind: 'leave', key: 'a' })
  })

  it('flush (a swipe, leaving the list): what was waiting is handed back to settle without playing', () => {
    const r = M.nextMotion(add(M.initialMotions(), { kind: 'leave', key: 'a' }, { kind: 'leave', key: 'b' }, { kind: 'enter', key: 'c' }))
    const f = M.flushMotions(r.state)
    expect(f.unplayed).toEqual([{ kind: 'leave', key: 'a' }, { kind: 'leave', key: 'b' }, { kind: 'enter', key: 'c' }])
    expect(M.nextMotion(f.state).item).toBeNull()
    expect(M.nextMotion(M.addMotion(f.state, { kind: 'leave', key: 'b' })).item).toBeNull() // an unplayed one counts as played
  })

  it('remembers a bounded number of played motions', () => {
    let s = M.initialMotions()
    for (let i = 0; i < M.MOTION_MEMORY + 50; i++) {
      const r = M.nextMotion(M.addMotion(s, { kind: 'leave', key: String(i) }))
      s = M.motionDone(r.state)
    }
    expect(s.played.length).toBe(M.MOTION_MEMORY)
  })
})

describe('chips when scrolled away: one at a time as events arrive, never twice', () => {
  const merged = (n) => ({ kind: 'merged', key: `r#${n}`, number: n })
  const came = (n) => ({ kind: 'came-in', key: `r#${n}`, number: n })

  it('says which MR and what happened, with the arrow up', () => {
    expect(M.chipText(merged(741))).toBe('↑ #741 merged above you')
    expect(M.chipText(came(753))).toBe('↑ #753 came in above you')
  })

  it('the first chip shows at once', () => {
    expect(M.addChip(M.initialChips(), merged(741)).current).toEqual(merged(741))
  })

  it('two at the same time are shown one each, in the order they came', () => {
    let s = M.addChip(M.addChip(M.initialChips(), came(753)), came(754))
    expect(s.current).toEqual(came(753))
    s = M.chipDone(s)
    expect(s.current).toEqual(came(754))
    s = M.chipDone(s)
    expect(s.current).toBeNull()
  })

  it('the same event never shows twice: not while it shows, not while it waits, not after', () => {
    let s = M.addChip(M.initialChips(), merged(741))
    s = M.addChip(s, merged(741))
    s = M.addChip(s, came(753))
    s = M.addChip(s, came(753))
    expect(s.queue).toEqual([came(753)])
    s = M.chipDone(M.chipDone(s))
    expect(M.addChip(s, merged(741)).current).toBeNull()
  })

  it('a merge and an arrival of the same MR are two different chips', () => {
    const s = M.addChip(M.addChip(M.initialChips(), came(9)), merged(9))
    expect(s.queue).toEqual([merged(9)])
  })

  it('each chip stays long enough to read, the time the mock-up showed it', () => {
    expect(M.CHIP_MS).toBe(2000)
  })

  it('chipDone with nothing showing changes nothing', () => {
    const s = M.initialChips()
    expect(M.chipDone(s)).toEqual(s)
  })
})

describe('frame: what the card looks like at time t (a pure function, so seeking and recording match playing)', () => {
  const plan = M.planMerge({ confirm: true })
  const fill = phase(plan, 'fill'), clear = phase(plan, 'clear'), close = phase(plan, 'close'), morph = phase(plan, 'morph'), tick = phase(plan, 'tick')
  const at = (t) => M.frame(plan.phases, t)

  it('before anything, the card is whole and nothing shows over it', () => {
    expect(at(0)).toMatchObject({ lo: 0, hi: 100, band: null, height: 1, opacity: 1 })
  })

  it('the bar becomes a circle during the morph, the tick draws after it', () => {
    const mid = at((morph.start + morph.end) / 2)
    expect(mid.check.morph).toBeGreaterThan(0)
    expect(mid.check.morph).toBeLessThan(1)
    expect(mid.check.tick).toBe(0)
    const later = at((tick.start + tick.end) / 2)
    expect(later.check.morph).toBe(1)
    expect(later.check.tick).toBeGreaterThan(0)
    expect(later.band).toBeNull()
  })

  it('the band is never wider than a third of the card, and never the whole card', () => {
    for (let t = fill.start; t <= clear.end; t += 10) {
      const f = at(t)
      if (!f.band) continue
      expect(f.band.hi - f.band.lo).toBeLessThanOrEqual(100 * M.LAG + 0.001)
      expect(f.band.lo).toBeGreaterThanOrEqual(f.lo)
    }
  })

  it('the space is empty once the closing sweep is past, and only then does it close', () => {
    expect(at(clear.end).lo).toBe(100)
    expect(at(clear.end).height).toBe(1)
    expect(at(close.end).height).toBe(0)
    expect(at((close.start + close.end) / 2).height).toBeGreaterThan(0)
  })

  it('the close is a spring with no bounce: the height never goes below zero or back up', () => {
    let last = 1
    for (let t = close.start; t <= close.end; t += 5) {
      const h = at(t).height
      expect(h).toBeGreaterThanOrEqual(0)
      expect(h).toBeLessThanOrEqual(last + 1e-9)
      last = h
    }
  })

  it('past the end it is the end, so an interrupted animation jumps straight there', () => {
    expect(at(plan.total + 5000)).toEqual(at(plan.total))
    expect(at(M.interrupt(plan).seekTo).height).toBe(0)
  })

  it('the card border is the brand blue while the band is on it', () => {
    expect(at((fill.start + clear.end) / 2).border).toBe(true)
    expect(at(close.end).border).toBe(false)
  })

  it('coming in, the card shows behind the fill', () => {
    const e = M.planEnter({})
    const g = phase(e, 'gapOpen'), r = phase(e, 'reveal')
    expect(M.frame(e.phases, 0).height).toBe(0)
    expect(M.frame(e.phases, g.end).height).toBe(1)
    const mid = M.frame(e.phases, (r.start + r.end) / 2)
    expect(mid.lo).toBe(0)
    expect(mid.band.hi).toBe(mid.hi)
    expect(M.frame(e.phases, e.total)).toMatchObject({ lo: 0, hi: 100, band: null, height: 1, opacity: 1 })
  })

  it('Reduce Motion never shows the band', () => {
    for (const p of [M.planMerge({ reduced: true, confirm: true }), M.planEnter({ reduced: true })]) {
      for (let t = 0; t <= p.total; t += 20) expect(M.frame(p.phases, t).band).toBeNull()
    }
    const r = M.planMerge({ reduced: true, confirm: true })
    expect(M.frame(r.phases, phase(r, 'checkFade').end).check).toMatchObject({ opacity: 1, morph: 1, tick: 1 })
  })
})

describe('onMergeEvent: nothing plays until GitHub confirms', () => {
  const s0 = M.initialGate()

  it('Approve alone plays nothing; GitHub confirming plays it', () => {
    const r1 = M.onMergeEvent(s0, { type: 'approved', key: 'a' })
    expect(r1.play).toEqual([])
    expect(r1.state.waiting).toEqual(['a'])
    const r2 = M.onMergeEvent(r1.state, { type: 'confirmed', key: 'a' })
    expect(r2.play).toEqual(['a'])
    expect(r2.state.waiting).toEqual([])
  })

  it('GitHub refusing plays nothing, and says which', () => {
    const r1 = M.onMergeEvent(s0, { type: 'approved', key: 'a' })
    const r2 = M.onMergeEvent(r1.state, { type: 'refused', key: 'a' })
    expect(r2).toMatchObject({ play: [], refused: 'a' })
    expect(r2.state.waiting).toEqual([])
  })

  it('a merge made elsewhere arrives already confirmed and plays; a duplicate does not play twice', () => {
    const r1 = M.onMergeEvent(s0, { type: 'confirmed', key: 'z' })
    expect(r1.play).toEqual(['z'])
    expect(M.onMergeEvent(r1.state, { type: 'confirmed', key: 'z' }).play).toEqual([])
  })

  it('ignores events it does not know', () => {
    expect(M.onMergeEvent(s0, { type: 'nonsense', key: 'a' })).toMatchObject({ play: [], state: s0 })
  })

  it('remembers a bounded number of confirmed merges', () => {
    let s = s0
    for (let i = 0; i < M.MOTION_MEMORY + 10; i++) s = M.onMergeEvent(s, { type: 'confirmed', key: String(i) }).state
    expect(s.done.length).toBe(M.MOTION_MEMORY)
  })
})

describe('gateEventOf: the merge op the main process pushes, as a gate event', () => {
  it('merging is an approval waiting for GitHub; merged is GitHub confirming', () => {
    expect(M.gateEventOf({ state: 'merging' })).toBe('approved')
    expect(M.gateEventOf({ state: 'merged' })).toBe('confirmed')
  })

  it('a failed, sent-back, interrupted or saved-for-later merge stops the wait', () => {
    for (const state of ['error', 'reengaged', 'interrupted', 'queued', 'idle']) expect(M.gateEventOf({ state })).toBe('refused')
  })

  it('no op, no event', () => {
    expect(M.gateEventOf(null)).toBeNull()
  })
})

describe('deferral: inside an MR, another tab, or the dashboard asleep', () => {
  it('plays at once when the list is on screen; holds it otherwise, once', () => {
    expect(M.routeMerge({ listVisible: true, pending: [] }, 'a').play).toEqual(['a'])
    const s = M.routeMerge(M.routeMerge({ listVisible: false, pending: [] }, 'a').state, 'a').state
    expect(s.pending).toEqual(['a'])
  })

  it('the MR you were inside still plays on the way back; the others are counted', () => {
    const back = M.onListShown({ listVisible: false, pending: ['a', 'b'] }, { focus: 'b' })
    expect(back.play).toEqual(['b'])
    expect(back.missed).toEqual(['a'])
    expect(back.note).toBe('1 merged while you were away')
  })

  it('merges you missed just show the result, with the count', () => {
    const back = M.onListShown({ listVisible: false, pending: ['a', 'b'] }, {})
    expect(back).toMatchObject({ play: [], missed: ['a', 'b'], note: '2 merged while you were away' })
    expect(M.onListShown({ listVisible: false, pending: [] }, {})).toMatchObject({ play: [], missed: [], note: null })
  })
})

describe('scrollPlan: the list changes length out of view, never under your eyes', () => {
  const base = { height: 120, gap: 16, scrollTop: 2000, viewport: 600 }

  it('on screen (even partly) it plays and the page does not move', () => {
    expect(M.scrollPlan({ ...base, top: 2100 })).toEqual({ where: 'in', play: true, scrollDelta: 0 })
    expect(M.scrollPlan({ ...base, top: 1950 }).where).toBe('in')
  })

  it('above you it goes or comes silently and the page shifts by exactly it', () => {
    expect(M.scrollPlan({ ...base, top: 100 })).toEqual({ where: 'above', play: false, scrollDelta: -136 })
    expect(M.scrollPlan({ ...base, top: 100, change: 'enter' })).toEqual({ where: 'above', play: false, scrollDelta: 136 })
    expect(M.scrollPlan({ ...base, top: 2000 - 120 }).where).toBe('above')
  })

  it('below you, nothing shifts', () => {
    expect(M.scrollPlan({ ...base, top: 2700 })).toEqual({ where: 'below', play: false, scrollDelta: 0 })
  })
})

describe('mergeShown: the list on screen while some cards are still leaving', () => {
  const k = (...keys) => keys.map((key) => ({ key }))

  it('a card GitHub dropped but still sweeping out stays where it was', () => {
    expect(M.mergeShown(k('a', 'b', 'c'), k('a', 'c'), new Set(['b'])).map((x) => x.key)).toEqual(['a', 'b', 'c'])
  })

  it('one at the top stays at the top, and new cards take their place in GitHub order', () => {
    expect(M.mergeShown(k('a', 'b'), k('n', 'b'), new Set(['a'])).map((x) => x.key)).toEqual(['a', 'n', 'b'])
  })

  it('cards not kept are gone, and an unchanged list is unchanged', () => {
    expect(M.mergeShown(k('a', 'b'), k('b'), new Set()).map((x) => x.key)).toEqual(['b'])
    expect(M.mergeShown(k('a', 'b'), k('a', 'b'), new Set(['a'])).map((x) => x.key)).toEqual(['a', 'b'])
  })

  it('the kept card is the one shown before (its last look), the rest are the new versions', () => {
    const before = [{ key: 'a', v: 1 }, { key: 'b', v: 1 }]
    const out = M.mergeShown(before, [{ key: 'b', v: 2 }], new Set(['a']))
    expect(out).toEqual([{ key: 'a', v: 1 }, { key: 'b', v: 2 }])
  })
})

describe('revertedBy: the "reverted by #N" pill on a Merged row', () => {
  const row = (number, title, repo = 'o/r', at = '2026-10-29T10:00:00Z') => ({ kind: 'merged', number, title, repo, url: `https://github.com/${repo}/pull/${number}`, at })

  it('a GitHub revert PR (Revert "<title>") marks the original', () => {
    const rows = [row(760, 'Revert "Vitals: disk headroom per machine"', 'o/r', '2026-10-29T12:00:00Z'), row(741, 'Vitals: disk headroom per machine')]
    expect(M.revertedBy(rows)).toEqual({ [rows[1].url]: 760 })
  })

  it('a revert that names the PR by number marks it too', () => {
    const rows = [row(761, 'Revert #741: it broke Vitals', 'o/r', '2026-10-29T12:00:00Z'), row(741, 'Vitals: disk headroom per machine')]
    expect(M.revertedBy(rows)).toEqual({ [rows[1].url]: 761 })
  })

  it('only within the same repo, only merged rows, never a PR reverting itself', () => {
    const rows = [row(760, 'Revert "Same title"', 'o/other'), row(741, 'Same title'), { ...row(742, 'Revert "Same title"'), kind: 'refused' }, row(743, 'Revert #743')]
    expect(M.revertedBy(rows)).toEqual({})
  })

  it('an ordinary title mentioning revert does not count', () => {
    expect(M.revertedBy([row(5, 'Docs: how to revert a change'), row(4, 'a change')])).toEqual({})
  })
})

describe('the blue, and the round-1 options the owner did not pick', () => {
  it('is the website brand blue, with the site focus-glow halo', () => {
    expect(M.BLUE.core).toBe('#198fd9')
    expect(M.BLUE.halo).toBe('rgba(102, 175, 233, 0.6)')
  })

  it('no cascade or together batches, no slide-back, no replay policies', () => {
    expect(M.planBatch).toBeUndefined()
    expect(M.planReturn).toBeUndefined()
    expect(M.AWAY).toBeUndefined()
  })
})

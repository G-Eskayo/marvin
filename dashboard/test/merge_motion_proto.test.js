import { describe, it, expect } from 'vitest'
// The #757 mock-up's choreography (docs/design/merge-animation-757/), round 2: the owner's answers on PR #761.
// A classic script so the prototype page opens straight from Finder (file://); it puts its API on globalThis.
// It moves to src/lib once the owner approves the motion.
import '../../docs/design/merge-animation-757/merge_motion.js'

const M = globalThis.MergeMotion
const phase = (plan, name, extra = {}) => plan.phases.find((p) => p.name === name && Object.entries(extra).every(([k, v]) => p[k] === v))
const SWEEPS = ['fill', 'clear', 'reveal']

describe('the pace: about 1.3x the first round', () => {
  it('every timing is the round-1 timing times 1.3', () => {
    expect(M.SPEED).toBe(1.3)
    for (const [k, base] of Object.entries(M.BASE)) expect(M.TIMING[k]).toBe(Math.round(base * 1.3))
  })

  it('a single merge in the list takes about 1.3x round 1 (1.1 s), so 1.3 to 1.6 s', () => {
    const total = M.planMerge({}).total
    expect(total).toBeGreaterThanOrEqual(1300)
    expect(total).toBeLessThanOrEqual(1600)
  })
})

describe('planMerge: leaving Open, in place', () => {
  const plan = M.planMerge({ layout: 'list' })
  const fill = phase(plan, 'fill'), clear = phase(plan, 'clear'), close = phase(plan, 'close')

  it('runs left to right, like everything else on the path', () => {
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
    // Same speed, so the blue band stays a third of the card wide all the way across.
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

  it('arriving in Merged is the same motion', () => {
    expect(M.planArrival({}).phases).toEqual(plan.phases)
    expect(M.planArrival({ layout: 'split' }).direction).toBe('ltr')
  })
})

describe('placeOf: the space opens where the MR belongs', () => {
  const byNumber = (a, b) => b.n - a.n // newest first, as an example order
  const list = [{ n: 760 }, { n: 752 }, { n: 744 }, { n: 731 }]

  it('in the middle', () => {
    expect(M.placeOf(list, { n: 748 }, byNumber)).toBe(2)
  })

  it('at the top and at the bottom', () => {
    expect(M.placeOf(list, { n: 799 }, byNumber)).toBe(0)
    expect(M.placeOf(list, { n: 700 }, byNumber)).toBe(4)
  })

  it('into an empty list', () => {
    expect(M.placeOf([], { n: 1 }, byNumber)).toBe(0)
  })

  it('after equal items, so it never jumps ahead of one already there', () => {
    expect(M.placeOf([{ n: 5 }, { n: 5 }], { n: 5 }, byNumber)).toBe(2)
  })
})

describe('planMerge: split view, one linear path', () => {
  const plan = M.planMerge({ layout: 'split' })
  const out = plan.phases.filter((p) => p.column === 'open'), into = plan.phases.filter((p) => p.column === 'merged')

  it('leaves Open left to right, and comes into Merged from the left', () => {
    expect(plan.direction).toBe('ltr')
    expect(out.length).toBeGreaterThan(0)
    expect(into.length).toBeGreaterThan(0)
  })

  it('the space in Merged opens a moment after the closing sweep finishes in Open', () => {
    const clear = out.find((p) => p.name === 'clear'), gap = into.find((p) => p.name === 'gapOpen')
    expect(gap.start - clear.end).toBe(M.TIMING.splitPause)
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

  it('coming in mirrors it: the space opens in 0.2 s, then the card fades in', () => {
    const plan = M.planEnter({ reduced: true })
    expect(plan.phases.map((p) => p.name)).toEqual(['gapOpen', 'fadeIn'])
    expect(phase(plan, 'gapOpen').end).toBe(200)
  })
})

describe('planQueue: several merges, one at a time, in the order GitHub confirms them', () => {
  const one = M.planMerge({}).total

  it('plays in confirmation order, not list order', () => {
    const plan = M.planQueue([{ key: 'a', at: 900 }, { key: 'b', at: 0 }, { key: 'c', at: 300 }])
    expect(plan.cards.map((c) => c.key)).toEqual(['b', 'c', 'a'])
  })

  it('each plays in full, gap closed, before the next starts', () => {
    const plan = M.planQueue([{ key: 'a', at: 0 }, { key: 'b', at: 10 }, { key: 'c', at: 20 }])
    expect(plan.cards.map((c) => c.offset)).toEqual([0, one, 2 * one])
    for (const [i, c] of plan.cards.entries()) {
      if (!i) continue
      const prev = plan.cards[i - 1].key
      expect(phase(plan, 'close', { key: prev }).end).toBeLessThanOrEqual(c.offset)
    }
  })

  it('one confirmed after the last has finished starts when it is confirmed, not earlier', () => {
    const plan = M.planQueue([{ key: 'a', at: 0 }, { key: 'b', at: one + 5000 }])
    expect(plan.cards[1].offset).toBe(one + 5000)
  })

  it('ties keep the order they came in', () => {
    expect(M.planQueue([{ key: 'x', at: 0 }, { key: 'y', at: 0 }]).cards.map((c) => c.key)).toEqual(['x', 'y'])
  })

  it('every phase carries its card key, and no two cards overlap', () => {
    const plan = M.planQueue([{ key: 'a', at: 0 }, { key: 'b', at: 0 }])
    expect(plan.phases.every((p) => p.key)).toBe(true)
    const endA = Math.max(...plan.phases.filter((p) => p.key === 'a').map((p) => p.end))
    const startB = Math.min(...plan.phases.filter((p) => p.key === 'b').map((p) => p.start))
    expect(startB).toBeGreaterThanOrEqual(endA)
  })

  it('under Reduce Motion it is still one at a time', () => {
    const r = M.planMerge({ reduced: true }).total
    expect(M.planQueue([{ key: 'a', at: 0 }, { key: 'b', at: 0 }], { reduced: true }).cards.map((c) => c.offset)).toEqual([0, r])
  })

  it('does not change the events it was given', () => {
    const events = [{ key: 'a', at: 5 }, { key: 'b', at: 0 }]
    M.planQueue(events)
    expect(events.map((e) => e.key)).toEqual(['a', 'b'])
  })

  it('an empty queue plays nothing', () => {
    expect(M.planQueue([]).total).toBe(0)
  })
})

describe('onMergeEvent: nothing plays until GitHub confirms', () => {
  const s0 = M.initialGate()

  it('Approve alone plays nothing; the card waits with its merge progress', () => {
    const r = M.onMergeEvent(s0, { type: 'approved', key: 'a' })
    expect(r.play).toEqual([])
    expect(r.state.waiting).toEqual(['a'])
  })

  it('GitHub confirming plays it', () => {
    const r1 = M.onMergeEvent(s0, { type: 'approved', key: 'a' })
    const r2 = M.onMergeEvent(r1.state, { type: 'confirmed', key: 'a' })
    expect(r2.play).toEqual(['a'])
    expect(r2.state.waiting).toEqual([])
  })

  it('GitHub refusing plays nothing: the card never moved, so nothing has to come back', () => {
    const r1 = M.onMergeEvent(s0, { type: 'approved', key: 'a' })
    const r2 = M.onMergeEvent(r1.state, { type: 'refused', key: 'a' })
    expect(r2.play).toEqual([])
    expect(r2.state.waiting).toEqual([])
    expect(r2.refused).toBe('a')
  })

  it('a merge made elsewhere (auto-merge, the other Mac) arrives already confirmed and plays', () => {
    expect(M.onMergeEvent(s0, { type: 'confirmed', key: 'z' }).play).toEqual(['z'])
  })

  it('a duplicate confirmation does not play twice', () => {
    const r1 = M.onMergeEvent(s0, { type: 'confirmed', key: 'a' })
    expect(M.onMergeEvent(r1.state, { type: 'confirmed', key: 'a' }).play).toEqual([])
  })

  it('ignores events it does not know, and leaves the state alone', () => {
    expect(M.onMergeEvent(s0, { type: 'nonsense', key: 'a' })).toMatchObject({ play: [], state: s0 })
  })
})

describe('deferral: inside an MR, or the dashboard asleep', () => {
  it('plays at once when the list is on screen', () => {
    const r = M.routeMerge({ listVisible: true, pending: [] }, 'a')
    expect(r.play).toEqual(['a'])
    expect(r.state.pending).toEqual([])
  })

  it('holds the leave while you are inside an MR, and plays it when you go back', () => {
    const r = M.routeMerge({ listVisible: false, pending: [] }, 'a')
    expect(r.play).toEqual([])
    const back = M.onListShown(r.state, { focus: 'a' })
    expect(back.play).toEqual(['a'])
    expect(back.state.pending).toEqual([])
  })

  it('does not queue the same MR twice', () => {
    const s = M.routeMerge(M.routeMerge({ listVisible: false, pending: [] }, 'a').state, 'a').state
    expect(s.pending).toEqual(['a'])
  })

  it('merges you missed always just show the result, with the count, however short the time away', () => {
    const back = M.onListShown({ listVisible: false, pending: ['a', 'b'] }, {})
    expect(back.play).toEqual([])
    expect(back.settled).toEqual(['a', 'b'])
    expect(back.note).toBe('2 merged while you were away')
  })

  it('the MR you were inside still plays on the way back; the others are counted', () => {
    const back = M.onListShown({ listVisible: false, pending: ['a', 'b'] }, { focus: 'b' })
    expect(back.play).toEqual(['b'])
    expect(back.settled).toEqual(['a'])
    expect(back.note).toBe('1 merged while you were away')
  })

  it('nothing pending, nothing to do', () => {
    expect(M.onListShown({ listVisible: false, pending: [] }, {})).toMatchObject({ play: [], settled: [], note: null })
  })
})

describe('scrollPlan: the list changes length out of view, never under your eyes', () => {
  const base = { height: 120, gap: 16, scrollTop: 2000, viewport: 600 }

  it('a card on screen plays normally and the page does not move', () => {
    expect(M.scrollPlan({ ...base, top: 2100 })).toEqual({ where: 'in', play: true, scrollDelta: 0 })
  })

  it('a card partly on screen still plays', () => {
    expect(M.scrollPlan({ ...base, top: 1950 }).where).toBe('in')
  })

  it('a card leaving above you goes silently and the page shifts up by it, so your place holds', () => {
    expect(M.scrollPlan({ ...base, top: 100 })).toEqual({ where: 'above', play: false, scrollDelta: -136 })
  })

  it('a card coming in above you arrives silently and the page shifts down by it', () => {
    expect(M.scrollPlan({ ...base, top: 100, change: 'enter' })).toEqual({ where: 'above', play: false, scrollDelta: 136 })
  })

  it('below you, nothing shifts either way', () => {
    expect(M.scrollPlan({ ...base, top: 2700 })).toEqual({ where: 'below', play: false, scrollDelta: 0 })
    expect(M.scrollPlan({ ...base, top: 2700, change: 'enter' })).toEqual({ where: 'below', play: false, scrollDelta: 0 })
  })

  it('a card ending exactly at the top edge is above you', () => {
    expect(M.scrollPlan({ ...base, top: 2000 - 120 }).where).toBe('above')
  })
})

describe('interrupt: a swipe (#756) mid-animation', () => {
  const plan = M.planMerge({})

  it('the animation finishes at once and the swipe goes now', () => {
    expect(M.interrupt(plan, 300)).toEqual({ seekTo: plan.total, navigateIn: 0 })
  })
})

describe('the round-1 options the owner did not pick are gone', () => {
  it('no cascade or together batches, no slide-back, no replay policies', () => {
    expect(M.planBatch).toBeUndefined()
    expect(M.planReturn).toBeUndefined()
    expect(M.AWAY).toBeUndefined()
  })
})

describe('the blue', () => {
  it('is the website brand blue, with the site focus-glow halo', () => {
    expect(M.BLUE.core).toBe('#198fd9')
    expect(M.BLUE.halo).toBe('rgba(102, 175, 233, 0.6)')
  })
})

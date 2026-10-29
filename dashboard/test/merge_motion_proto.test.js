import { describe, it, expect } from 'vitest'
// The #757 mock-up's choreography (docs/design/merge-animation-757/). A classic script so the prototype page opens
// straight from Finder (file://); it puts its API on globalThis. It moves to src/lib once the owner approves the motion.
import '../../docs/design/merge-animation-757/merge_motion.js'

const M = globalThis.MergeMotion
const phase = (plan, name) => plan.phases.find((p) => p.name === name)
const MOVING = ['sweep', 'slide', 'trail', 'close', 'gapOpen', 'arrive', 'slideBack', 'gapReopen']

describe('planMerge: leaving Open in the list', () => {
  const plan = M.planMerge({ layout: 'list' })

  it('sweeps, then the card follows the sweep out to the left', () => {
    expect(plan.exit).toBe('left')
    expect(phase(plan, 'sweep').start).toBe(0)
    expect(phase(plan, 'slide').start).toBeGreaterThan(0)
    expect(phase(plan, 'slide').start).toBeLessThan(phase(plan, 'sweep').end)
  })

  it('leaves a trail that outlasts the card', () => {
    expect(phase(plan, 'trail').end).toBeGreaterThan(phase(plan, 'slide').end)
  })

  it('closes the gap only once the card is mostly gone, so nothing slides under it', () => {
    const slide = phase(plan, 'slide')
    expect(phase(plan, 'close').start).toBeGreaterThanOrEqual(slide.start + 0.8 * (slide.end - slide.start))
  })

  it('reports a total that covers every phase', () => {
    expect(plan.total).toBe(Math.max(...plan.phases.map((p) => p.end)))
  })

  it('has no arrival in the list layout: Merged is another tab', () => {
    expect(phase(plan, 'arrive')).toBeUndefined()
  })
})

describe('planArrival: arriving in Merged', () => {
  it('opens a space at the top, then slides in from the right on the Merged tab', () => {
    const plan = M.planArrival({ layout: 'list' })
    expect(plan.entry).toBe('right')
    expect(phase(plan, 'gapOpen').start).toBe(0)
    expect(phase(plan, 'arrive').start).toBeGreaterThanOrEqual(phase(plan, 'gapOpen').end)
  })

  it('in the split view enters from the side it left by default, and from the right when chosen', () => {
    expect(M.planArrival({ layout: 'split' }).entry).toBe('left')
    expect(M.planArrival({ layout: 'split', splitEntry: 'right' }).entry).toBe('right')
  })
})

describe('planMerge: split view', () => {
  const plan = M.planMerge({ layout: 'split' })

  it('slides right out of Open', () => {
    expect(plan.exit).toBe('right')
  })

  it('opens the space in Merged a moment after the card has left Open', () => {
    const gap = plan.phases.find((p) => p.name === 'gapOpen' && p.column === 'merged')
    expect(gap.start).toBeGreaterThan(phase(plan, 'slide').end)
    expect(gap.start - phase(plan, 'slide').end).toBe(M.TIMING.splitPause)
  })

  it('slides the card into the space only after it has opened', () => {
    const gap = plan.phases.find((p) => p.name === 'gapOpen')
    const arrive = plan.phases.find((p) => p.name === 'arrive')
    expect(arrive.start).toBeGreaterThanOrEqual(gap.end)
  })
})

describe('Reduce Motion: a simple fade', () => {
  for (const layout of ['list', 'split']) {
    it(`nothing moves in the ${layout} layout`, () => {
      const plan = M.planMerge({ layout, reduced: true })
      expect(plan.phases.filter((p) => MOVING.includes(p.name))).toEqual([])
      expect(phase(plan, 'fade')).toBeDefined()
      expect(plan.total).toBeLessThanOrEqual(500)
    })
  }

  it('arrival and a correction fade too', () => {
    expect(M.planArrival({ reduced: true }).phases.map((p) => p.name)).toEqual(['fadeIn'])
    expect(M.planReturn({ reduced: true }).phases.filter((p) => MOVING.includes(p.name))).toEqual([])
  })
})

describe('planBatch: several merges at once', () => {
  const keys = ['a', 'b', 'c']

  it('cascade staggers the cards and closes the gap once, after the last one leaves', () => {
    const plan = M.planBatch(keys, { mode: 'cascade' })
    expect(plan.cards.map((c) => c.offset)).toEqual([0, M.TIMING.cascade, 2 * M.TIMING.cascade])
    const closes = plan.phases.filter((p) => p.name === 'close')
    expect(closes).toHaveLength(1)
    const lastSlide = Math.max(...plan.phases.filter((p) => p.name === 'slide').map((p) => p.end))
    expect(closes[0].start).toBeGreaterThanOrEqual(lastSlide - 0.2 * M.TIMING.slide)
  })

  it('together starts every card at once', () => {
    expect(M.planBatch(keys, { mode: 'together' }).cards.every((c) => c.offset === 0)).toBe(true)
  })

  it('one at a time plays each in full, gap closed, before the next', () => {
    const plan = M.planBatch(keys, { mode: 'sequence' })
    const single = M.planMerge({}).total
    expect(plan.cards.map((c) => c.offset)).toEqual([0, single, 2 * single])
    expect(plan.phases.filter((p) => p.name === 'close')).toHaveLength(3)
  })

  it('under Reduce Motion is one fade for all, whatever the mode', () => {
    const plan = M.planBatch(keys, { mode: 'sequence', reduced: true })
    expect(plan.cards.every((c) => c.offset === 0)).toBe(true)
    expect(plan.phases.filter((p) => p.name === 'fade')).toHaveLength(1)
  })

  it('an empty batch plays nothing', () => {
    expect(M.planBatch([], {}).total).toBe(0)
  })
})

describe('deferral: inside an MR, or the dashboard asleep', () => {
  it('plays at once when the list is on screen', () => {
    const r = M.routeMerge({ listVisible: true, pending: [] }, 'a')
    expect(r.play).toEqual(['a'])
    expect(r.state.pending).toEqual([])
  })

  it('holds the slide-out while you are inside an MR, and plays it when you go back', () => {
    const r = M.routeMerge({ listVisible: false, pending: [], hiddenSince: 1000 }, 'a')
    expect(r.play).toEqual([])
    const back = M.onListShown(r.state, { now: 5000 })
    expect(back.play).toEqual(['a'])
    expect(back.state.pending).toEqual([])
  })

  it('does not queue the same MR twice', () => {
    const s = M.routeMerge(M.routeMerge({ listVisible: false, pending: [] }, 'a').state, 'a').state
    expect(s.pending).toEqual(['a'])
  })

  it('after a long sleep shows the result with a count instead of replaying', () => {
    const state = { listVisible: false, pending: ['a', 'b'], hiddenSince: 0 }
    const back = M.onListShown(state, { now: M.AWAY.maxAwayMs + 1 })
    expect(back.play).toEqual([])
    expect(back.settled).toEqual(['a', 'b'])
    expect(back.note).toBe('2 merged while you were away')
  })

  it('too many missed merges also just shows the result', () => {
    const pending = Array.from({ length: M.AWAY.maxReplay + 1 }, (_, i) => `k${i}`)
    const back = M.onListShown({ listVisible: false, pending, hiddenSince: 0 }, { now: 10 })
    expect(back.play).toEqual([])
    expect(back.settled).toHaveLength(pending.length)
  })

  it('the other policies: always replay, or never', () => {
    const state = { listVisible: false, pending: ['a'], hiddenSince: 0 }
    expect(M.onListShown(state, { now: 1e9, policy: 'replay-all' }).play).toEqual(['a'])
    expect(M.onListShown(state, { now: 1, policy: 'show-result' }).play).toEqual([])
  })

  it('the MR you were inside always plays on the way back, however long you read it', () => {
    const state = { listVisible: false, pending: ['a', 'b'], hiddenSince: 0 }
    const back = M.onListShown(state, { now: M.AWAY.maxAwayMs * 5, focus: 'b' })
    expect(back.play).toEqual(['b'])
    expect(back.settled).toEqual(['a'])
    expect(back.note).toBe('1 merged while you were away')
  })

  it('the MR you were inside plays even under "just show the result"', () => {
    const back = M.onListShown({ listVisible: false, pending: ['a'], hiddenSince: 0 }, { now: 1, policy: 'show-result', focus: 'a' })
    expect(back).toMatchObject({ play: ['a'], settled: [], note: null })
  })

  it('nothing pending, nothing to do', () => {
    const back = M.onListShown({ listVisible: false, pending: [], hiddenSince: 0 }, { now: 1 })
    expect(back).toMatchObject({ play: [], settled: [], note: null })
  })
})

describe('scrollPlan: scrolled far down the list', () => {
  const base = { height: 120, gap: 16, scrollTop: 2000, viewport: 600 }

  it('a card on screen plays normally and the page does not move', () => {
    expect(M.scrollPlan({ ...base, top: 2100 })).toEqual({ where: 'in', play: true, scrollDelta: 0 })
  })

  it('a card partly on screen still plays', () => {
    expect(M.scrollPlan({ ...base, top: 1950 }).where).toBe('in')
  })

  it('a card above you leaves silently and the page keeps your place', () => {
    expect(M.scrollPlan({ ...base, top: 100 })).toEqual({ where: 'above', play: false, scrollDelta: -136 })
  })

  it('a card below you leaves silently and nothing shifts', () => {
    expect(M.scrollPlan({ ...base, top: 2700 })).toEqual({ where: 'below', play: false, scrollDelta: 0 })
  })
})

describe('interrupt: a swipe (#756) mid-animation', () => {
  const plan = M.planMerge({})

  it('finish: jumps to the end state and lets the swipe go now', () => {
    expect(M.interrupt(plan, 300, 'finish')).toEqual({ seekTo: plan.total, navigateIn: 0 })
  })

  it('wait: the swipe goes once the animation ends', () => {
    expect(M.interrupt(plan, 300, 'wait')).toEqual({ seekTo: null, navigateIn: plan.total - 300 })
  })

  it('after the end there is nothing to wait for', () => {
    expect(M.interrupt(plan, plan.total + 50, 'wait').navigateIn).toBe(0)
  })
})

describe('planReturn: a merge GitHub then refuses', () => {
  it('reopens the gap and slides the card back from the side it left', () => {
    const plan = M.planReturn({ layout: 'list' })
    expect(plan.entry).toBe('left')
    expect(phase(plan, 'slideBack').start).toBeGreaterThanOrEqual(phase(plan, 'gapReopen').end)
    expect(phase(plan, 'pulse').tone).toBe('amber')
  })

  it('in the split view it comes back from the right', () => {
    expect(M.planReturn({ layout: 'split' }).entry).toBe('right')
  })
})

describe('the blue', () => {
  it('is the website brand blue, with the site focus-glow halo', () => {
    expect(M.BLUE.core).toBe('#198fd9')
    expect(M.BLUE.halo).toBe('rgba(102, 175, 233, 0.6)')
  })
})

import { describe, it, expect } from 'vitest'
import { startHistory, visit, back, forward, canGoBack, canGoForward, current, sameScreen, MAX_ENTRIES } from '../src/lib/nav_history.js'
import { createScrollArea } from '../src/lib/scroll_places.js'

const list = (tab = 'mr-review') => ({ tab, item: null })
const pr = (n) => ({ tab: 'mr-review', item: `pr:G-Eskayo/marvin#${n}` })
const doc = (p) => ({ tab: 'docs', item: `doc:marvin/${p}` })

// One history for the whole dashboard (#756): each entry is a screen, a tab plus what's open in it (null = its list).
describe('back and forward', () => {
  it('back from an open MR returns to the list; forward reopens the MR', () => {
    let h = visit(startHistory(list()), pr(175))
    const b = back(h)
    expect(b.screen).toEqual(list())
    expect(current(b.history)).toEqual(list())
    const f = forward(b.history)
    expect(f.screen).toEqual(pr(175))
  })

  it('after switching tabs, back returns to the previous tab, as it was left', () => {
    let h = startHistory(list())
    h = visit(h, pr(175))
    h = visit(h, list('docs'))
    h = visit(h, doc('README.md'))
    expect(back(h).screen).toEqual(list('docs'))
    expect(back(back(h).history).screen).toEqual(pr(175))
  })

  it('a new visit after going back drops the forward entries, as a browser does', () => {
    let h = visit(visit(startHistory(list()), pr(1)), pr(2))
    h = back(h).history // at pr 1
    h = visit(h, pr(3))
    expect(canGoForward(h)).toBe(false)
    expect(back(h).screen).toEqual(pr(1))
  })

  it('revisiting the screen you are on adds nothing (a re-render, a refresh, a double click)', () => {
    let h = visit(startHistory(list()), pr(1))
    const again = visit(h, { ...pr(1) })
    expect(again).toBe(h)
    expect(back(again).screen).toEqual(list())
  })
})

describe('nothing left', () => {
  it('back at the start and forward at the end say so instead of moving (the bounce), and change nothing', () => {
    const h = startHistory(list())
    const b = back(h)
    expect(b.screen).toBe(null)
    expect(b.edge).toBe('start')
    expect(b.history).toBe(h)
    const f = forward(h)
    expect(f.screen).toBe(null)
    expect(f.edge).toBe('end')
    expect(canGoBack(h)).toBe(false)
    expect(canGoForward(h)).toBe(false)
  })

  it('an item that is gone (merged, denied, deleted) is skipped, not reopened broken', () => {
    let h = startHistory(list())
    h = visit(h, pr(175))
    h = visit(h, list('docs'))
    const gone = (s) => s.item !== pr(175).item
    expect(back(h, { available: gone }).screen).toEqual(list())
    expect(canGoBack(visit(startHistory(pr(175)), list('docs')), { available: gone })).toBe(false)
  })

  it('skipping never lands on the screen you are already on', () => {
    // list → pr 9 → list again (the app returned to the list after Approve): back skips the merged PR AND the
    // identical list, so there is nothing to go back to rather than a swipe that does nothing visible.
    let h = visit(visit(startHistory(list()), pr(9)), list())
    const r = back(h, { available: (s) => s.item !== pr(9).item })
    expect(r.screen).toBe(null)
    expect(r.edge).toBe('start')
  })

  it('history is bounded: the oldest screens are forgotten, the current one never', () => {
    let h = startHistory(list())
    for (let i = 0; i < MAX_ENTRIES + 50; i++) h = visit(h, pr(i))
    expect(h.entries.length).toBe(MAX_ENTRIES)
    expect(current(h)).toEqual(pr(MAX_ENTRIES + 49))
    let steps = 0
    while (canGoBack(h)) { h = back(h).history; steps++ }
    expect(steps).toBe(MAX_ENTRIES - 1)
  })

  it('junk screens are refused rather than stored', () => {
    const h = startHistory(list())
    for (const junk of [null, undefined, {}, { tab: '' }, { tab: 7 }]) expect(visit(h, junk)).toBe(h)
    expect(() => startHistory(null)).toThrow()
  })

  it('history never mutates: an old value still describes its own moment', () => {
    const h0 = startHistory(list())
    const h1 = visit(h0, pr(1))
    back(h1)
    expect(h0.entries).toHaveLength(1)
    expect(current(h1)).toEqual(pr(1))
  })

  it('sameScreen treats a missing item and null alike', () => {
    expect(sameScreen({ tab: 'docs' }, { tab: 'docs', item: null })).toBe(true)
    expect(sameScreen(doc('a'), doc('b'))).toBe(false)
  })
})

// Scroll restore isn't stored in history: going back shows the same screen, and #755's scroll places key the scroll
// position by the screen, so the place comes back with it. This drives both together the way the app does.
describe('back restores the place in the list (with #755)', () => {
  class Box {
    constructor(h) { this.clientHeight = 800; this.scrollHeight = h; this._t = 0 }
    get scrollTop() { return this._t }
    set scrollTop(v) { this._t = Math.max(0, Math.min(v, this.scrollHeight - this.clientHeight)) }
  }
  function app() {
    const box = new Box(5000)
    const area = createScrollArea({ name: 'main', store: new Map(), schedule: (f) => f(), now: () => 0 })
    area.attach(box)
    // What the tabs do with a screen: the tab is the area's base, the open item its view's part.
    const show = (s) => {
      box.scrollHeight = s.item ? 1000 : 5000
      area.setBase(s.tab)
      area.setSegment('open-item', s.item)
    }
    const scroll = (t) => { box.scrollTop = t; area.onScroll() }
    return { box, show, scroll }
  }

  it('list → MR → back lands where you clicked; forward reopens the MR where you were in it', () => {
    const { box, show, scroll } = app()
    let h = startHistory(list()); show(current(h))
    scroll(2754)
    h = visit(h, pr(175)); show(current(h))
    expect(box.scrollTop).toBe(0)
    scroll(120)
    let r = back(h); h = r.history; show(r.screen)
    expect(box.scrollTop).toBe(2754)
    r = forward(h); h = r.history; show(r.screen)
    expect(box.scrollTop).toBe(120)
  })

  it("back across a tab switch restores the other tab's place too", () => {
    const { box, show, scroll } = app()
    let h = startHistory(list()); show(current(h))
    scroll(1800)
    h = visit(h, list('health')); show(current(h))
    scroll(400)
    const r = back(h); show(r.screen)
    expect(box.scrollTop).toBe(1800)
  })
})

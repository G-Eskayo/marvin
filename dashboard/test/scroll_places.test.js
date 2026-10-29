import { describe, it, expect } from 'vitest'
import { createScrollArea, placeKey } from '../src/lib/scroll_places.js'

// A scroll box that behaves like the browser's: scrollTop is clamped to what the current content allows, and a swap
// of content keeps the old offset (clamped), which is exactly how #755's jump to the bottom happens.
class Box {
  constructor(contentHeight, clientHeight = 800) {
    this.clientHeight = clientHeight
    this.scrollHeight = contentHeight
    this._top = 0
  }
  get scrollTop() { return this._top }
  set scrollTop(v) { this._top = Math.max(0, Math.min(v, this.scrollHeight - this.clientHeight)) }
  get max() { return this.scrollHeight - this.clientHeight }
  swap(contentHeight) { this.scrollHeight = contentHeight; this.scrollTop = this._top }
}

function setup({ store = new Map(), list = 5000, now = () => 0 } = {}) {
  const box = new Box(list)
  const area = createScrollArea({ name: 'main', store, schedule: (fn) => fn(), now })
  area.attach(box)
  area.setBase('mr-review')
  // The user scrolls: the browser moves the box, then fires a scroll event.
  const scroll = (top) => { box.scrollTop = top; area.onScroll() }
  return { box, area, store, scroll }
}

describe('#755: opening an item never inherits the list position', () => {
  it('reproduces the jump without the area: the MR opens at its own bottom', () => {
    const box = new Box(5000)
    box.scrollTop = 2754
    box.swap(1015) // the MR detail replaces the list in the same <main>
    expect(box.scrollTop).toBe(box.max) // the bug: the MR opens scrolled all the way down
  })

  it('an MR opened from far down the list opens at its top', () => {
    const { box, area, scroll } = setup()
    scroll(2754)
    box.swap(1015)
    area.setSegment('open-prs', 'pr:G-Eskayo/marvin#175')
    expect(box.scrollTop).toBe(0)
  })

  it('going back lands exactly where you clicked, the part the owner said matters most', () => {
    const { box, area, scroll } = setup()
    scroll(2754)
    box.swap(1015)
    area.setSegment('open-prs', 'pr:G-Eskayo/marvin#175')
    scroll(120) // read a bit of the MR
    box.swap(5000)
    area.setSegment('open-prs', null)
    expect(box.scrollTop).toBe(2754)
  })

  it('reopening the same item returns to where you were in it; a different item starts at its top', () => {
    const { box, area, scroll } = setup()
    box.swap(3000); area.setSegment('open-prs', 'pr:a'); scroll(900)
    box.swap(5000); area.setSegment('open-prs', null)
    box.swap(3000); area.setSegment('open-prs', 'pr:b')
    expect(box.scrollTop).toBe(0)
    box.swap(5000); area.setSegment('open-prs', null)
    box.swap(3000); area.setSegment('open-prs', 'pr:a')
    expect(box.scrollTop).toBe(900)
  })

  it('each tab keeps its own place', () => {
    const { box, area, scroll } = setup()
    scroll(2000)
    area.setBase('health')
    expect(box.scrollTop).toBe(0)
    scroll(300)
    area.setBase('mr-review')
    expect(box.scrollTop).toBe(2000)
    area.setBase('health')
    expect(box.scrollTop).toBe(300)
  })

  it('places outlive the component: a remounted tab finds the same store', () => {
    const store = new Map()
    const first = setup({ store })
    first.scroll(1500)
    first.area.detach()
    const again = setup({ store })
    expect(again.box.scrollTop).toBe(1500)
  })
})

describe('content that arrives after the switch', () => {
  it('the list is still loading when you come back: the place is reached once it is tall enough', () => {
    const { box, area, scroll } = setup()
    scroll(2754)
    box.swap(1015); area.setSegment('open-prs', 'pr:x')
    box.swap(400) // back, but the list rerenders short (loading) first
    area.setSegment('open-prs', null)
    expect(box.scrollTop).toBe(0)
    area.onScroll() // the clamp's own scroll event must not overwrite the saved place
    box.swap(2000); area.onContentResize()
    expect(box.scrollTop).toBe(1200)
    box.swap(5000); area.onContentResize()
    expect(box.scrollTop).toBe(2754)
    box.swap(9000); area.onContentResize() // reached: later growth does not move you
    scroll(2800)
    expect(area.saved()).toBe(2800)
  })

  it('the user scrolling, clicking or typing stops a pending restore: their hand wins', () => {
    const { box, area, scroll } = setup()
    scroll(2754)
    box.swap(1015); area.setSegment('open-prs', 'pr:x')
    box.swap(400); area.setSegment('open-prs', null)
    area.onUserInput()
    box.swap(5000); area.onContentResize()
    expect(box.scrollTop).toBe(0)
  })

  it('a pending restore gives up after a few seconds, so a late refresh never yanks the page', () => {
    let t = 0
    const { box, area, scroll } = setup({ now: () => t })
    scroll(2754)
    box.swap(1015); area.setSegment('open-prs', 'pr:x')
    box.swap(400); area.setSegment('open-prs', null)
    t = 10_000
    box.swap(5000); area.onContentResize()
    expect(box.scrollTop).toBe(0)
  })

  it('a deliberate jump (search hit, heading link) cancels the pending restore', () => {
    const { box, area, scroll } = setup()
    scroll(2754)
    box.swap(400); area.setSegment('docs', 'doc:a')
    box.swap(400); area.setSegment('docs', 'doc:b')
    area.cancelRestore()
    box.swap(5000); box.scrollTop = 50 // the jump, once the doc has drawn
    area.onContentResize()
    expect(box.scrollTop).toBe(50)
  })
})

describe('several views in one area', () => {
  it('nested views make one key, the same for the same screen whatever order they registered in', () => {
    expect(placeKey('mr-review', new Map([['a', 'merged'], ['b', 'pr:1']]))).toBe(placeKey('mr-review', new Map([['b', 'pr:1'], ['a', 'merged']])))
    expect(placeKey('mr-review', new Map([['a', 'merged']]))).not.toBe(placeKey('mr-review', new Map([['a', 'open']])))
    expect(placeKey('mr-review', new Map([['a', null]]))).toBe(placeKey('mr-review', new Map()))
  })

  it('Open and Merged lists keep separate places, and a merged PR returns to the merged list', () => {
    const { box, area, scroll } = setup()
    area.setSegment('toggle', 'open'); scroll(1000)
    area.setSegment('toggle', 'merged'); expect(box.scrollTop).toBe(0); scroll(3000)
    area.setSegment('history', 'pr:9'); expect(box.scrollTop).toBe(0)
    area.setSegment('history', null); expect(box.scrollTop).toBe(3000)
    area.setSegment('toggle', 'open'); expect(box.scrollTop).toBe(1000)
  })

  it('several changes in one render settle once, on the final screen', () => {
    const queued = []
    const box = new Box(5000)
    const area = createScrollArea({ name: 'main', store: new Map(), schedule: (fn) => queued.push(fn), now: () => 0 })
    area.attach(box)
    area.setBase('mr-review'); area.setSegment('toggle', 'open'); queued.splice(0).forEach((f) => f())
    box.scrollTop = 700; area.onScroll()
    area.setSegment('toggle', 'merged')
    area.setSegment('history', 'pr:1')
    area.removeSegment('history')
    area.setSegment('toggle', 'open') // net: nothing changed
    queued.splice(0).forEach((f) => f())
    expect(box.scrollTop).toBe(700)
  })

  it('a detached area ignores late events instead of throwing', () => {
    const { area } = setup()
    area.detach()
    expect(() => { area.onScroll(); area.onContentResize(); area.onUserInput(); area.setSegment('x', 'y') }).not.toThrow()
  })

  it('the place store is bounded: the oldest places are forgotten first', () => {
    const store = new Map()
    const { area, scroll } = setup({ store })
    for (let i = 0; i < 600; i++) { area.setSegment('open-prs', `pr:${i}`); scroll(10) }
    expect(store.size).toBeLessThanOrEqual(500)
    expect(store.has(`main|${placeKey('mr-review', new Map([['open-prs', 'pr:599']]))}`)).toBe(true)
  })
})

describe('wiring', () => {
  // A slot from useId would be a fresh counter on every client mount, so a tab switched away and back never found its
  // place (caught live on the first build). Slots are fixed names, one per view.
  it('every view names a fixed slot, and no two views share one', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const dir = path.resolve(import.meta.dirname, '../src/components')
    const calls = fs.readdirSync(dir).filter((f) => f.endsWith('.jsx') && f !== 'ScrollPlaces.jsx')
      .flatMap((f) => [...fs.readFileSync(path.join(dir, f), 'utf8').matchAll(/useScrollPlace\(([^,)]*)/g)].map((m) => ({ f, slot: m[1].trim() })))
    expect(calls.length).toBeGreaterThanOrEqual(6)
    for (const c of calls) expect(c.slot, c.f).toMatch(/^'[a-z-]+'$/)
    const slots = calls.map((c) => c.slot)
    expect(new Set(slots).size).toBe(slots.length)
  })
})

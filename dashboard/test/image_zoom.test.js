import { describe, it, expect } from 'vitest'
import { fitScale, clampScale, stepScale, toggleScale, zoomScroll, wheelZoomFactor, viewerKey, MIN_SCALE, MAX_SCALE } from '../src/lib/image_zoom.js'

const VIEW = { w: 1200, h: 800 }

describe('fitScale: how an image first opens', () => {
  it('a big landscape image fits inside the window', () => {
    expect(fitScale({ w: 2400, h: 1200 }, VIEW)).toBeCloseTo(0.5)
    expect(fitScale({ w: 1600, h: 1600 }, VIEW)).toBeCloseTo(0.5)
  })
  it('a small image opens at its own size, never blown up', () => {
    expect(fitScale({ w: 300, h: 200 }, VIEW)).toBe(1)
  })
  it('a tall full-page screenshot opens fit-to-width (to scroll), not shrunk to a thin column', () => {
    const s = fitScale({ w: 1440, h: 9000 }, VIEW)
    expect(s).toBeCloseTo(1200 / 1440)
    expect(1440 * s).toBeCloseTo(1200)            // fills the width
    expect(9000 * s).toBeGreaterThan(VIEW.h)      // and scrolls
  })
  it('a merely portrait image (not a full page) still fits whole', () => {
    expect(fitScale({ w: 1000, h: 1500 }, VIEW)).toBeCloseTo(800 / 1500)
  })
  it('survives zero, missing and junk sizes', () => {
    for (const [n, v] of [[{ w: 0, h: 0 }, VIEW], [null, VIEW], [{ w: 100, h: 100 }, { w: 0, h: 0 }], [{ w: NaN, h: 5 }, VIEW], [undefined, undefined]]) {
      const s = fitScale(n, v)
      expect(Number.isFinite(s) && s > 0).toBe(true)
    }
  })
})

describe('scale steps', () => {
  it('clamps to the allowed range and survives junk', () => {
    expect(clampScale(100)).toBe(MAX_SCALE)
    expect(clampScale(0)).toBe(MIN_SCALE)
    expect(clampScale(-3)).toBe(MIN_SCALE)
    expect(clampScale(NaN)).toBe(1)
  })
  it('+ and − are inverse steps and stay in range', () => {
    expect(stepScale(stepScale(1, 1), -1)).toBeCloseTo(1)
    expect(stepScale(MAX_SCALE, 1)).toBe(MAX_SCALE)
    expect(stepScale(MIN_SCALE, -1)).toBe(MIN_SCALE)
  })
  it('double-click toggles Fit ↔ 100%, and zooms to 200% when the fit already is 100%', () => {
    expect(toggleScale(0.4, 0.4)).toBe(1)
    expect(toggleScale(1, 0.4)).toBe(0.4)
    expect(toggleScale(2.5, 0.4)).toBe(0.4)
    expect(toggleScale(1, 1)).toBe(2)
  })
})

describe('zoomScroll: the point under the cursor stays put', () => {
  it('keeps the image pixel under the pointer fixed when zooming in on a big image', () => {
    // 2000px image at 0.5 = 1000px in a 800px viewport, scrolled 100, pointer at 300 → image px (100+300)/0.5 = 800
    const next = zoomScroll({ scroll: 100, point: 300, client: 800, natural: 2000, from: 0.5, to: 1 })
    expect((next + 300) / 1).toBeCloseTo(800)
  })
  it('accounts for the centring margin when the image is smaller than the viewport', () => {
    // 400px image at 1 in a 1000px viewport sits at offset 300. Pointer at 500 = image px 200 (its middle).
    const next = zoomScroll({ scroll: 0, point: 500, client: 1000, natural: 400, from: 1, to: 4 })
    // At 4x the image is 1600 wide (no margin); image px 200 → 800 content px; keep it under the pointer at 500.
    expect(next).toBeCloseTo(300)
  })
  it('never returns a negative scroll, and survives junk', () => {
    expect(zoomScroll({ scroll: 0, point: 0, client: 800, natural: 100, from: 1, to: 0.5 })).toBe(0)
    expect(zoomScroll({})).toBe(0)
  })
})

describe('wheel and keys', () => {
  it('pinch / ⌘-scroll up zooms in, down zooms out; plain scroll does not zoom', () => {
    expect(wheelZoomFactor({ deltaY: -10, ctrlKey: true })).toBeGreaterThan(1)
    expect(wheelZoomFactor({ deltaY: 10, metaKey: true })).toBeLessThan(1)
    expect(wheelZoomFactor({ deltaY: 10 })).toBeNull()
    expect(wheelZoomFactor({ deltaY: 100000, ctrlKey: true })).toBeGreaterThan(0)   // bounded, never 0 or negative
  })
  it('maps keys to viewer actions', () => {
    expect(viewerKey({ key: 'Escape' })).toBe('close')
    expect(viewerKey({ key: 'ArrowRight' })).toBe('next')
    expect(viewerKey({ key: 'ArrowLeft' })).toBe('prev')
    expect(viewerKey({ key: '+' })).toBe('in')
    expect(viewerKey({ key: '=' })).toBe('in')
    expect(viewerKey({ key: '-' })).toBe('out')
    expect(viewerKey({ key: '0' })).toBe('fit')
    expect(viewerKey({ key: 'a' })).toBeNull()
    expect(viewerKey({ key: '+', target: { tagName: 'INPUT' } })).toBeNull()   // typing elsewhere is left alone
    expect(viewerKey({ key: 'Escape', target: { tagName: 'INPUT' } })).toBe('close')
  })
})

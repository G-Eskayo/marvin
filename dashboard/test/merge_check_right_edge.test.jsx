import { describe, it, expect } from 'vitest'
// The check mark grows out of the merge bar's right end, so the bar collapses left to right into it, the same way the
// sweep goes (owner, 2026-10-30). It used to shrink to the middle of the bar.
import { checkRect } from '../src/components/MergeMotion.jsx'

const bar = { left: 20, top: 100, width: 400, height: 4 }
const right = (r) => r.left + r.width

describe('the check mark sits at the right end of the merge bar', () => {
  it('starts as the whole bar', () => {
    expect(checkRect(bar, 0)).toEqual(bar)
  })
  it('keeps its right edge on the bar\'s right end all the way through the morph', () => {
    for (const m of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]) expect(right(checkRect(bar, m))).toBeCloseTo(right(bar))
  })
  it('ends as a 22 px circle at the right end, not in the middle', () => {
    const r = checkRect(bar, 1)
    expect(r.width).toBe(22)
    expect(r.height).toBe(22)
    expect(r.left).toBe(right(bar) - 22)
    expect(r.left).toBeGreaterThan(bar.left + bar.width / 2)
  })
  it('only moves left to right: its left edge never goes backwards as it shrinks', () => {
    let prev = -Infinity
    for (let m = 0; m <= 1.0001; m += 0.05) { const l = checkRect(bar, m).left; expect(l).toBeGreaterThanOrEqual(prev); prev = l }
  })
  it('stays centred on the bar vertically', () => {
    for (const m of [0, 0.5, 1]) { const r = checkRect(bar, m); expect(r.top + r.height / 2).toBeCloseTo(bar.top + bar.height / 2) }
  })
  it('a bar narrower than the circle still ends with its right edge on the bar\'s end', () => {
    const tiny = { left: 0, top: 0, width: 10, height: 2 }
    expect(right(checkRect(tiny, 1))).toBeCloseTo(10)
  })
})

import { describe, it, expect } from 'vitest'
import { createMergeWatch } from '../src/lib/merge_watch.js'

// The merge motion's ears (marvin#838): the main process's merge pushes, routed to the list on screen or held for it.
function fakeApi() {
  let cb = null
  return { api: { mr: { onMergeEvent: (f) => { cb = f; return () => {} } } }, push: (url, op) => cb(url, op), subscribed: () => !!cb }
}
function listener() {
  const calls = { play: [], refused: [] }
  return { calls, play: (k) => calls.play.push(k), refused: (k, why) => calls.refused.push([k, why]) }
}

describe('mergeWatch', () => {
  it('subscribes once, however many times the list mounts', () => {
    let n = 0
    const w = createMergeWatch()
    const api = { mr: { onMergeEvent: () => { n++; return () => {} } } }
    w.attach(api); w.attach(api)
    expect(n).toBe(1)
  })

  it('nothing plays on Approve; it plays when GitHub confirms, with the list on screen', () => {
    const w = createMergeWatch(), f = fakeApi(), l = listener()
    w.attach(f.api)
    w.show(l)
    f.push('u1', { state: 'merging' })
    expect(l.calls.play).toEqual([])
    expect(w.isWaiting('u1')).toBe(true)
    f.push('u1', { state: 'merged' })
    expect(l.calls.play).toEqual(['u1'])
    expect(w.isWaiting('u1')).toBe(false)
    expect(w.isConfirmed('u1')).toBe(true)
  })

  it('several confirmed play in the order GitHub confirmed them, each once', () => {
    const w = createMergeWatch(), f = fakeApi(), l = listener()
    w.attach(f.api); w.show(l)
    for (const u of ['b', 'a', 'b', 'c', 'a']) f.push(u, { state: 'merged' })
    expect(l.calls.play).toEqual(['b', 'a', 'c'])
  })

  it('a refusal plays nothing and raises the notice with GitHub\'s reason', () => {
    const w = createMergeWatch(), f = fakeApi(), l = listener()
    w.attach(f.api); w.show(l)
    f.push('u1', { state: 'merging' })
    f.push('u1', { state: 'error', reason: 'GitHub refused the merge: a required check failed.' })
    expect(l.calls.play).toEqual([])
    expect(l.calls.refused).toEqual([['u1', 'GitHub refused the merge: a required check failed.']])
  })

  it('a sent-back or saved-for-later merge ends the wait without the notice (the card says why)', () => {
    const w = createMergeWatch(), f = fakeApi(), l = listener()
    w.attach(f.api); w.show(l)
    f.push('u1', { state: 'merging' })
    f.push('u1', { state: 'reengaged', reason: 'tests failed after the rebase' })
    f.push('u2', { state: 'queued', reason: 'no Mac can merge' })
    expect(l.calls.refused).toEqual([])
    expect(w.isWaiting('u1')).toBe(false)
  })

  it('merged while the list is hidden: counted, and shown as a result when the list is back', () => {
    const w = createMergeWatch(), f = fakeApi(), l = listener()
    w.attach(f.api)
    f.push('a', { state: 'merged' }); f.push('b', { state: 'merged' })
    const back = w.show(l)
    expect(l.calls.play).toEqual([])
    expect(back).toMatchObject({ play: [], missed: ['a', 'b'], note: '2 merged while you were away' })
  })

  it('the MR you were inside plays on the way back', () => {
    const w = createMergeWatch(), f = fakeApi(), l = listener()
    w.attach(f.api); w.show(l); w.hide()
    f.push('a', { state: 'merged' })
    expect(w.show(l, { focus: 'a' })).toMatchObject({ play: ['a'], missed: [], note: null })
  })

  it('after hide, the old listener hears nothing', () => {
    const w = createMergeWatch(), f = fakeApi(), l = listener()
    w.attach(f.api); w.show(l); w.hide()
    f.push('a', { state: 'merged' })
    expect(l.calls.play).toEqual([])
  })

  it('tells subscribers something changed, until they unsubscribe; ignores junk', () => {
    const w = createMergeWatch(), f = fakeApi()
    w.attach(f.api)
    let n = 0
    const off = w.onChange(() => n++)
    f.push('a', { state: 'merging' })
    f.push('a', null)
    f.push(null, { state: 'merged' })
    off()
    f.push('a', { state: 'merged' })
    expect(n).toBe(1)
  })
})

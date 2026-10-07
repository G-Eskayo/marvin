import { describe, it, expect } from 'vitest'
import { getQueue, clearQueueCache } from '../electron/main/queue.js'
import { describeQueueRow } from '../src/components/NextUpQueue.jsx'

describe('getQueue', () => {
  it('returns the rows, caches, and reports a failed read as an error (never as an empty queue)', async () => {
    clearQueueCache()
    let calls = 0
    const run = async () => { calls++; return '[{"position":1,"number":5}]' }
    expect(await getQueue({ run, now: 1000 })).toEqual({ queue: [{ position: 1, number: 5 }], error: null })
    await getQueue({ run, now: 20000 })
    expect(calls).toBe(1)
    clearQueueCache()
    const bad = await getQueue({ run: async () => { throw new Error('gh down') }, now: 1000 })
    expect(bad.queue).toEqual([])
    expect(bad.error).toMatch(/gh down/)
  })
})

describe('describeQueueRow', () => {
  it('pairs the number with its title, marks the first row, shows priority and machines', () => {
    const v = describeQueueRow({ position: 1, repo: 'o/clarity', project: 'clarity', number: 36, title: 'Speech languages', priority: 'p1', machines: ['mac-mini-1', 'macbook-pro-1'] })
    expect(v).toMatchObject({ key: 'o/clarity#36', next: true, label: 'clarity #36 Speech languages', priority: 'P1', machines: 'mac-mini-1, macbook-pro-1' })
  })
  it('later rows are not next; no priority and no machines read plainly', () => {
    expect(describeQueueRow({ position: 2, repo: 'o/a', project: 'a', number: 1, title: 't', priority: null, machines: [] })).toMatchObject({ next: false, priority: null, machines: 'any machine' })
  })
})

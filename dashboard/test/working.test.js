import { describe, it, expect } from 'vitest'
import { buildWorkingNow } from '../electron/main/working.js'

const job = (over = {}) => ({ job: 'x', label: 'Ticket pipeline', status: 'idle', current: null, last: null, ...over })
const idle = { busy: false, task: null, startedAt: null }

describe('buildWorkingNow', () => {
  it('is empty when nothing is running, and remembers the last thing that finished', () => {
    const r = buildWorkingNow({
      dispatch: idle,
      jobs: [
        job({ label: 'Tidy agent', last: { finishedAt: '2026-10-05T10:00:00Z', summary: 'filed 7', status: 'passed' } }),
        job({ label: 'Ticket pipeline', last: { finishedAt: '2026-10-05T12:00:00Z', summary: 'no ready tickets', status: 'passed' } })
      ]
    })
    expect(r.items).toEqual([])
    expect(r.last).toMatchObject({ label: 'Ticket pipeline', summary: 'no ready tickets', finishedAt: '2026-10-05T12:00:00Z' })
  })

  it('lists a dispatched task first, then each running agent with the step it is on', () => {
    const r = buildWorkingNow({
      dispatch: { busy: true, task: 'ticket G-Eskayo/clarity-captions#17: Auto-scroll', startedAt: '2026-10-05T12:00:00Z' },
      jobs: [
        job({ label: 'Project catalog', status: 'running', current: { step: 'Local folders', detail: '14 found', startedAt: '2026-10-05T12:01:00Z' } }),
        job({ label: 'Tidy agent', status: 'idle' })
      ]
    })
    expect(r.items.map((i) => [i.kind, i.label])).toEqual([['task', 'ticket G-Eskayo/clarity-captions#17: Auto-scroll'], ['job', 'Project catalog']])
    expect(r.items[1].detail).toBe('Local folders — 14 found')
  })

  it('does not count a crashed or failed agent as working', () => {
    const r = buildWorkingNow({ dispatch: idle, jobs: [job({ status: 'crashed' }), job({ status: 'failed' })] })
    expect(r.items).toEqual([])
  })

  it('copes with no jobs at all', () => {
    expect(buildWorkingNow({ dispatch: idle, jobs: [] })).toEqual({ items: [], last: null })
  })
})

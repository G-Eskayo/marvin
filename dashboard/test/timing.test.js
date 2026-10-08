import { describe, it, expect, vi } from 'vitest'
import { EventEmitter } from 'events'
import { timed, instrumentIpc, timeRequest, rankTimings } from '../electron/main/timing.js'

// #236: every dashboard IPC call and webhook route is timed, so "the dashboard is slow" becomes a ranked list.
let clock = 0
const now = () => clock

describe('timed', () => {
  it('records name, duration and success of an async call, and returns its result', async () => {
    const record = vi.fn()
    clock = 1000
    const fn = timed('ipc', 'mr:list', async () => { clock = 1250; return 'ok' }, { record, now })
    await expect(fn()).resolves.toBe('ok')
    expect(record).toHaveBeenCalledWith({ side: 'ipc', name: 'mr:list', ms: 250, ok: true })
  })

  it('records a failure and rethrows it unchanged', async () => {
    const record = vi.fn()
    const err = new Error('gh down')
    const fn = timed('ipc', 'mr:approve', async () => { throw err }, { record, now })
    await expect(fn()).rejects.toBe(err)
    expect(record).toHaveBeenCalledWith(expect.objectContaining({ name: 'mr:approve', ok: false }))
  })

  it('a broken recorder never breaks the call', async () => {
    const fn = timed('ipc', 'x', async () => 1, { record: () => { throw new Error('disk full') }, now })
    await expect(fn()).resolves.toBe(1)
  })
})

describe('instrumentIpc', () => {
  it('wraps every handler registered afterwards, passing its arguments through', async () => {
    const handlers = {}
    const ipcMain = { handle: (channel, fn) => { handlers[channel] = fn } }
    const record = vi.fn()
    instrumentIpc(ipcMain, { record, now })
    ipcMain.handle('mr:ticketContext', async (_e, ref, repo) => `${ref}@${repo}`)
    await expect(handlers['mr:ticketContext']({}, '#5', 'G-Eskayo/marvin')).resolves.toBe('#5@G-Eskayo/marvin')
    expect(record).toHaveBeenCalledWith(expect.objectContaining({ side: 'ipc', name: 'mr:ticketContext', ok: true }))
  })
})

describe('timeRequest (webhook routes)', () => {
  it('records method and path (no query string) when the response finishes, with ok from the status code', () => {
    const record = vi.fn()
    const res = Object.assign(new EventEmitter(), { statusCode: 500 })
    clock = 0
    timeRequest({ method: 'POST', url: '/approve?x=1' }, res, { record, now })
    clock = 61000
    res.emit('finish')
    expect(record).toHaveBeenCalledWith({ side: 'webhook', name: 'POST /approve', ms: 61000, ok: false })
  })
})

describe('rankTimings', () => {
  it('ranks calls by total time, with count, p50, p95 and max', () => {
    const rows = [
      ...Array.from({ length: 19 }, () => ({ name: 'mr:list', side: 'ipc', ms: 100 })),
      { name: 'mr:list', side: 'ipc', ms: 2000 },
      { name: 'POST /approve', side: 'webhook', ms: 61000 },
      { name: 'metrics:index', side: 'ipc', ms: 5 }
    ]
    const ranked = rankTimings(rows)
    expect(ranked.map((r) => r.name)).toEqual(['POST /approve', 'mr:list', 'metrics:index'])
    expect(ranked[1]).toMatchObject({ side: 'ipc', count: 20, totalMs: 3900, p50: 100, p95: 100, max: 2000 })
  })
})

import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { readRegistry, loadBoard } from '../electron/main/boards.js'

const tmp = () => mkdtempSync(path.join(tmpdir(), 'boards-'))

describe('readRegistry', () => {
  it('returns [] when there is no registry yet', () => {
    const d = tmp()
    try {
      expect(readRegistry(path.join(d, 'nope.json'))).toEqual([])
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('returns the boards, and [] for a corrupt file rather than throwing', () => {
    const d = tmp()
    try {
      const f = path.join(d, 'r.json')
      writeFileSync(f, JSON.stringify({ boards: [{ repo: 'o/r', name: 'r' }] }))
      expect(readRegistry(f)).toEqual([{ repo: 'o/r', name: 'r' }])
      writeFileSync(f, '{bad')
      expect(readRegistry(f)).toEqual([])
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

describe('loadBoard', () => {
  it('asks gh for issues and PRs of the repo and builds the board', async () => {
    const calls = []
    const gh = async (args) => {
      calls.push(args)
      if (args[0] === 'issue' && args.includes('closed')) return JSON.stringify([])
      if (args[0] === 'issue') {
        return JSON.stringify([
          { number: 1, title: 'T', state: 'OPEN', labels: [{ name: 'ready-for-agent' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' }
        ])
      }
      return JSON.stringify([])
    }
    const board = await loadBoard('o/r', { gh, stagesFor: () => ({}), liveNumbers: new Set() })
    expect(calls.map((c) => c[0])).toEqual(['issue', 'issue', 'pr'])
    // every open ticket is fetched on its own (never crowded out by closed ones), closed ones are recent only
    expect(calls[0]).toContain('open')
    expect(calls[1]).toContain('closed')
    expect(calls.every((c) => c.includes('o/r'))).toBe(true)
    expect(board.columns.find((c) => c.id === 'ready').cards[0].title).toBe('T')
  })

  it('stamps when the data was fetched, so the board can say how fresh it is', async () => {
    const before = Date.now()
    const board = await loadBoard('o/r', { gh: async () => '[]', stagesFor: () => ({}), liveNumbers: new Set() })
    const at = Date.parse(board.fetchedAt)
    expect(at).toBeGreaterThanOrEqual(before)
    expect(at).toBeLessThanOrEqual(Date.now())
  })

  it('surfaces a gh failure as an error naming the repo', async () => {
    const gh = async () => {
      throw new Error('auth')
    }
    await expect(loadBoard('o/r', { gh })).rejects.toThrow(/o\/r/)
  })
})

import { withProjectStatus } from '../electron/main/boards.js'

describe('withProjectStatus', () => {
  const cat = { projects: [{ id: 'marvin', status: 'active', lastActivity: '2026-10-05T12:00:00Z' }, { id: 'old-thing', status: 'dormant', lastActivity: '2026-09-01T00:00:00Z' }, { id: 'gone', status: 'archived' }] }

  it('adds each board\'s project status from the catalog, matching by project id', () => {
    const out = withProjectStatus([{ repo: 'G-Eskayo/marvin' }, { repo: 'G-Eskayo/Old_Thing' }, { repo: 'G-Eskayo/gone' }], cat)
    expect(out.map((b) => b.status)).toEqual(['active', 'dormant', 'archived'])
  })

  it('carries through lastActivity from the catalog when present', () => {
    const out = withProjectStatus([{ repo: 'G-Eskayo/marvin' }, { repo: 'G-Eskayo/Old_Thing' }, { repo: 'G-Eskayo/gone' }], cat)
    expect(out[0].lastActivity).toBe('2026-10-05T12:00:00Z')
    expect(out[1].lastActivity).toBe('2026-09-01T00:00:00Z')
    expect(out[2].lastActivity).toBe(null)
  })

  it('treats a board with no catalog entry (or no catalog yet) as recent, never hides it', () => {
    expect(withProjectStatus([{ repo: 'G-Eskayo/unknown' }], cat)[0].status).toBe('recent')
    expect(withProjectStatus([{ repo: 'G-Eskayo/marvin' }], null)[0].status).toBe('recent')
  })
})

import { liveTicketNumbers } from '../electron/main/boards.js'

describe('liveTicketNumbers', () => {
  it('reads which project\'s ticket is running from the dispatch label, so marvin #7 is not mistaken for clarity #7', () => {
    const task = 'ticket G-Eskayo/clarity-captions#7: Auto-scroll'
    expect([...liveTicketNumbers('G-Eskayo/clarity-captions', task)]).toEqual([7])
    expect([...liveTicketNumbers('G-Eskayo/marvin', task)]).toEqual([])
  })

  it('still reads the older unqualified label as marvin\'s', () => {
    expect([...liveTicketNumbers('G-Eskayo/marvin', 'ticket #42: something')]).toEqual([42])
    expect([...liveTicketNumbers('G-Eskayo/clarity-captions', 'ticket #42: something')]).toEqual([])
  })

  it('is empty when nothing is running', () => {
    expect([...liveTicketNumbers('G-Eskayo/marvin', null)]).toEqual([])
  })
})

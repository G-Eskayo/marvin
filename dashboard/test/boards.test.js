import { describe, it, expect, beforeEach } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { readRegistry, loadBoard, clearCrossProjectCache } from '../electron/main/boards.js'

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
  beforeEach(() => clearCrossProjectCache())

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

  it('merges cross-repo issues and partitions them, excluding foreign project labels from own issues', async () => {
    const gh = async (args) => {
      if (args[0] === 'issue' && args.includes('closed')) return JSON.stringify([])
      if (args[0] === 'issue') {
        return JSON.stringify([
          { number: 1, title: 'Own', state: 'OPEN', labels: [{ name: 'ready-for-agent' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' },
          { number: 2, title: 'Has foreign label', state: 'OPEN', labels: [{ name: 'project:portfolio-website-updater' }, { name: 'ready-for-agent' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' }
        ])
      }
      return JSON.stringify([])
    }
    const registryRepos = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/portfolio-website-updater', name: 'Portfolio' }
    ]
    const board = await loadBoard('G-Eskayo/marvin', {
      gh,
      registryRepos,
      stagesFor: () => ({}),
      liveNumbers: new Set()
    })
    // Only ticket #1 should be in the board (ticket #2 has a foreign project label)
    const readyCards = board.columns.find((c) => c.id === 'ready').cards
    expect(readyCards.length).toBe(1)
    expect(readyCards[0].number).toBe(1)
    // otherProjects should have a tally for portfolio
    expect(board.otherProjects).toContainEqual(
      expect.objectContaining({ projectId: 'portfolio-website-updater', count: 1 })
    )
  })

  it('caches cross-repo issues like getBoardData (5 min TTL)', async () => {
    const calls = { issue: 0, search: 0 }
    const gh = async (args) => {
      if (args[0] === 'issue') calls.issue++
      if (args[0] === 'search') calls.search++
      return JSON.stringify([])
    }
    const registryRepos = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/portfolio-website-updater', name: 'Portfolio' }
    ]
    // Load board twice within TTL
    await loadBoard('G-Eskayo/marvin', { gh, registryRepos, stagesFor: () => ({}), liveNumbers: new Set() })
    await loadBoard('G-Eskayo/marvin', { gh, registryRepos, stagesFor: () => ({}), liveNumbers: new Set() })
    // search should only be called once (cached), issue list called twice
    expect(calls.search).toBe(1)
    expect(calls.issue).toBe(4) // 2 issue calls per loadBoard (open, closed)
  })

  it('merges cross-project issues from multiple foreign repos with no number collision', async () => {
    const calls = []
    const gh = async (args) => {
      calls.push(args)
      if (args[0] === 'issue' && args.includes('closed')) return JSON.stringify([])
      if (args[0] === 'issue') {
        return JSON.stringify([
          { number: 7, title: 'Own ticket 7', state: 'OPEN', labels: [{ name: 'ready-for-agent' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' }
        ])
      }
      // Cross-project search returns issues #7 from two different repos with ready-for-agent label
      if (args[0] === 'search') {
        return JSON.stringify([
          { number: 7, title: 'Portfolio #7', state: 'OPEN', repository: { nameWithOwner: 'G-Eskayo/portfolio-website-updater' }, labels: [{ name: 'project:marvin' }, { name: 'ready-for-agent' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' },
          { number: 7, title: 'Clarity #7', state: 'OPEN', repository: { nameWithOwner: 'G-Eskayo/clarity-captions' }, labels: [{ name: 'project:marvin' }, { name: 'ready-for-agent' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' }
        ])
      }
      return JSON.stringify([])
    }
    const registryRepos = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/portfolio-website-updater', name: 'Portfolio' },
      { repo: 'G-Eskayo/clarity-captions', name: 'Clarity' }
    ]
    const board = await loadBoard('G-Eskayo/marvin', { gh, registryRepos, stagesFor: () => ({}), liveNumbers: new Set() })
    // All three #7s should appear on the board (no collision)
    const readyCards = board.columns.find((c) => c.id === 'ready').cards
    const card7s = readyCards.filter((c) => c.number === 7)
    expect(card7s.length).toBe(3)
    // Own-repo card has no repo field (undefined), foreign cards have repo field
    const repos = card7s.map((c) => c.repo).sort()
    expect(repos).toContain('G-Eskayo/clarity-captions')
    expect(repos).toContain('G-Eskayo/portfolio-website-updater')
    expect(repos).toContain(undefined) // own-repo card
    // Verify that the search was called
    expect(calls.some((c) => c[0] === 'search')).toBe(true)
  })

  it('clearCrossProjectCache invalidates the cache on the next fetch', async () => {
    let callCount = 0
    const gh = async (args) => {
      if (args[0] === 'search') callCount++
      return JSON.stringify([])
    }
    const registryRepos = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/portfolio-website-updater', name: 'Portfolio' }
    ]
    // First load caches the result
    await loadBoard('G-Eskayo/marvin', { gh, registryRepos, stagesFor: () => ({}), liveNumbers: new Set() })
    expect(callCount).toBe(1)
    // Second load uses cache
    await loadBoard('G-Eskayo/marvin', { gh, registryRepos, stagesFor: () => ({}), liveNumbers: new Set() })
    expect(callCount).toBe(1)
    // Clear cache
    clearCrossProjectCache()
    // Third load fetches again
    await loadBoard('G-Eskayo/marvin', { gh, registryRepos, stagesFor: () => ({}), liveNumbers: new Set() })
    expect(callCount).toBe(2)
  })
})

import { withProjectStatus } from '../electron/main/boards.js'

describe('withProjectStatus', () => {
  const cat = { projects: [{ id: 'marvin', status: 'active', lastActivity: '2026-10-08T12:00:00Z' }, { id: 'old-thing', status: 'dormant', lastActivity: null }, { id: 'gone', status: 'archived', lastActivity: '2026-01-01T00:00:00Z' }] }

  it('adds each board\'s project status from the catalog, matching by project id', () => {
    const out = withProjectStatus([{ repo: 'G-Eskayo/marvin' }, { repo: 'G-Eskayo/Old_Thing' }, { repo: 'G-Eskayo/gone' }], cat)
    expect(out.map((b) => b.status)).toEqual(['active', 'dormant', 'archived'])
  })

  it('treats a board with no catalog entry (or no catalog yet) as recent, never hides it', () => {
    expect(withProjectStatus([{ repo: 'G-Eskayo/unknown' }], cat)[0].status).toBe('recent')
    expect(withProjectStatus([{ repo: 'G-Eskayo/marvin' }], null)[0].status).toBe('recent')
  })

  it('passes through lastActivity from the catalog', () => {
    const out = withProjectStatus([{ repo: 'G-Eskayo/marvin' }, { repo: 'G-Eskayo/Old_Thing' }], cat)
    expect(out[0].lastActivity).toBe('2026-10-08T12:00:00Z')
    expect(out[1].lastActivity).toBe(null)
  })

  it('sets lastActivity to undefined when no catalog is provided', () => {
    const out = withProjectStatus([{ repo: 'G-Eskayo/marvin' }], null)
    expect(out[0].lastActivity).toBeUndefined()
  })
})

import { liveTicketNumbers, fetchCrossProjectIssues } from '../electron/main/boards.js'

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

describe('fetchCrossProjectIssues', () => {
  beforeEach(() => clearCrossProjectCache())

  it('fetches issues from other registered repos labelled with this project id', async () => {
    const calls = []
    const gh = async (args) => {
      calls.push(args)
      return JSON.stringify([
        { number: 7, title: 'Cross-repo', state: 'OPEN', repository: { nameWithOwner: 'G-Eskayo/portfolio-website-updater' }, labels: [{ name: 'project:marvin' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' },
        { number: 3, title: 'Another', state: 'CLOSED', repository: { nameWithOwner: 'G-Eskayo/portfolio-website-updater' }, labels: [{ name: 'project:marvin' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' }
      ])
    }
    const registryRepos = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/portfolio-website-updater', name: 'Portfolio' }
    ]
    const issues = await fetchCrossProjectIssues('G-Eskayo/marvin', registryRepos, gh)
    expect(issues.length).toBe(2)
    expect(issues[0].repo).toBe('G-Eskayo/portfolio-website-updater')
    expect(issues[1].repo).toBe('G-Eskayo/portfolio-website-updater')
    expect(calls.length).toBe(1)
    expect(calls[0][0]).toBe('search')
    expect(calls[0]).toContain('issues')
    expect(calls[0]).toContain('--label')
    expect(calls[0]).toContain('project:marvin')
  })

  it('asks gh search only for fields it supports, and enough of them (gh search has no stateReason; default limit is 30)', async () => {
    // the fields `gh search issues --json` accepts (gh 2.x); asking for any other fails the whole call
    const SEARCH_FIELDS = new Set(['assignees', 'author', 'authorAssociation', 'body', 'closedAt', 'commentsCount', 'createdAt', 'id',
      'isLocked', 'isPullRequest', 'labels', 'number', 'repository', 'state', 'title', 'updatedAt', 'url'])
    const calls = []
    const gh = async (args) => { calls.push(args); return '[]' }
    await fetchCrossProjectIssues('G-Eskayo/marvin', [{ repo: 'G-Eskayo/marvin' }, { repo: 'G-Eskayo/x' }], gh)
    const fields = calls[0][calls[0].indexOf('--json') + 1].split(',')
    expect(fields.filter((f) => !SEARCH_FIELDS.has(f))).toEqual([])
    expect(Number(calls[0][calls[0].indexOf('--limit') + 1])).toBeGreaterThanOrEqual(200)
  })

  it('a failing search leaves the board loadable with no cross-project tickets', async () => {
    const gh = async () => { throw new Error('Unknown JSON field') }
    expect(await fetchCrossProjectIssues('G-Eskayo/marvin', [{ repo: 'G-Eskayo/marvin' }, { repo: 'G-Eskayo/x' }], gh)).toEqual([])
  })

  it('skips the call entirely when there are no other registered repos', async () => {
    const calls = []
    const gh = async (args) => { calls.push(args); return '[]' }
    const registryRepos = [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }]
    const issues = await fetchCrossProjectIssues('G-Eskayo/marvin', registryRepos, gh)
    expect(issues).toEqual([])
    expect(calls.length).toBe(0)
  })

  it('returns empty when no issues match the project label', async () => {
    const gh = async () => JSON.stringify([])
    const registryRepos = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/portfolio-website-updater', name: 'Portfolio' }
    ]
    const issues = await fetchCrossProjectIssues('G-Eskayo/marvin', registryRepos, gh)
    expect(issues).toEqual([])
  })

  it('normalizes state from search output (lowercase) to match issue list (uppercase)', async () => {
    const gh = async () => JSON.stringify([
      { number: 1, title: 'Open', state: 'open', repository: { nameWithOwner: 'G-Eskayo/portfolio-website-updater' }, labels: [], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' },
      { number: 2, title: 'Closed', state: 'closed', repository: { nameWithOwner: 'G-Eskayo/portfolio-website-updater' }, labels: [], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' }
    ])
    const registryRepos = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/portfolio-website-updater', name: 'Portfolio' }
    ]
    const issues = await fetchCrossProjectIssues('G-Eskayo/marvin', registryRepos, gh)
    expect(issues[0].state).toBe('OPEN')
    expect(issues[1].state).toBe('CLOSED')
  })
})

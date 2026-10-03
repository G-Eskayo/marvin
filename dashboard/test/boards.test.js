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
      if (args[0] === 'issue') {
        return JSON.stringify([
          { number: 1, title: 'T', state: 'OPEN', labels: [{ name: 'ready-for-agent' }], body: '', url: 'u', createdAt: '2026-10-01T00:00:00Z' }
        ])
      }
      return JSON.stringify([])
    }
    const board = await loadBoard('o/r', { gh, stagesFor: () => ({}), liveNumbers: new Set() })
    expect(calls.map((c) => c[0])).toEqual(['issue', 'pr'])
    expect(calls.every((c) => c.includes('o/r'))).toBe(true)
    expect(board.columns.find((c) => c.id === 'ready').cards[0].title).toBe('T')
  })

  it('surfaces a gh failure as an error naming the repo', async () => {
    const gh = async () => {
      throw new Error('auth')
    }
    await expect(loadBoard('o/r', { gh })).rejects.toThrow(/o\/r/)
  })
})

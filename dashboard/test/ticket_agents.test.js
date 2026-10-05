import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { groupProposals, readTicketAgents } from '../electron/main/ticket_agents.js'

const p = (agent, number, op, arg, why = 'because', repo = 'G-Eskayo/marvin', title = `T${number}`) => ({ agent, repo, number, title, op, arg, why })

describe('groupProposals', () => {
  it('groups by agent, then by ticket, summarising the changes in plain words', () => {
    const g = groupProposals([
      p('prioritize', 1, 'remove_label', 'priority:p3'),
      p('prioritize', 1, 'add_label', 'priority:p1', 'unblocks 4 tickets'),
      p('stale_claims', 2, 'remove_label', 'claimed:mac-mini'),
      p('stale_claims', 2, 'comment', 'long text here')
    ])
    expect(g.prioritize).toEqual([{ repo: 'G-Eskayo/marvin', number: 1, title: 'T1', changes: ['− priority:p3', '+ priority:p1'], why: 'unblocks 4 tickets' }])
    expect(g.stale_claims[0].changes).toEqual(['− claimed:mac-mini', 'comment'])
  })

  it('keeps tickets from different projects apart even when the numbers match', () => {
    const g = groupProposals([p('triage', 5, 'add_label', 'needs-info', 'x', 'o/a'), p('triage', 5, 'add_label', 'needs-info', 'x', 'o/b')])
    expect(g.triage).toHaveLength(2)
  })
})

describe('readTicketAgents', () => {
  const withDir = (fn) => {
    const dir = mkdtempSync(path.join(tmpdir(), 'tka-'))
    try {
      return fn(dir)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  }

  it('returns null before any run, and the mode, date and grouped proposals after one', () =>
    withDir((dir) => {
      const pp = path.join(dir, 'p.json')
      expect(readTicketAgents({ proposalsPath: pp, configPath: path.join(dir, 'c.json') })).toBeNull()
      writeFileSync(pp, JSON.stringify({ generated_at: 't', effective_mode: 'propose', act_after: '2026-10-12', by_agent: { prioritize: { mode: 'propose', planned: 1 } }, proposals: [p('prioritize', 1, 'add_label', 'priority:p2')] }))
      const r = readTicketAgents({ proposalsPath: pp, configPath: path.join(dir, 'c.json') })
      expect(r.actAfter).toBe('2026-10-12')
      expect(r.byAgent.prioritize.mode).toBe('propose')
      expect(r.grouped.prioritize).toHaveLength(1)
    }))

  it('a corrupt file is treated as no run yet', () =>
    withDir((dir) => {
      const pp = path.join(dir, 'p.json')
      writeFileSync(pp, '{bad')
      expect(readTicketAgents({ proposalsPath: pp, configPath: path.join(dir, 'c.json') })).toBeNull()
    }))
})

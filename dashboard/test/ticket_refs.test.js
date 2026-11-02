import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { prTicketRefs, ticketLinked } from '../electron/main/ticket_refs.js'

const { cases } = JSON.parse(readFileSync(new URL('./fixtures/pr_ticket_refs_cases.json', import.meta.url), 'utf-8'))

describe('prTicketRefs: the shared cases (lib/pr_ticket_check.py runs the same file)', () => {
  for (const c of cases) {
    it(c.name, () => {
      expect(prTicketRefs(c.body, c.prRepo).map((r) => [`${r.repo}#${r.number}`, r.relation])).toEqual(c.refs)
    })
  }
})

describe('prTicketRefs: inputs that are not text', () => {
  it('treats null and undefined bodies as empty', () => {
    expect(prTicketRefs(null, 'o/r')).toEqual([])
    expect(prTicketRefs(undefined, 'o/r')).toEqual([])
  })
  it('returns numbers, not strings', () => {
    expect(prTicketRefs('Part of #9', 'o/r')[0].number).toBe(9)
  })
})

describe('ticketLinked', () => {
  it('matches the ticket by repo and number, ignoring repo-name case', () => {
    const pr = { repo: 'G-Eskayo/marvin-instance', body: 'Closes g-eskayo/MARVIN#623' }
    expect(ticketLinked(pr, 'G-Eskayo/marvin', 623)).toBe('closes')
    expect(ticketLinked(pr, 'G-Eskayo/marvin-instance', 623)).toBe(null)
  })
  it('a bare #N belongs to the PR\'s own repo, falling back to the given default', () => {
    expect(ticketLinked({ body: 'Part of #4' }, 'o/r', 4, 'o/r')).toBe('part-of')
    expect(ticketLinked({ body: 'Part of #4' }, 'o/x', 4, 'o/r')).toBe(null)
  })
})

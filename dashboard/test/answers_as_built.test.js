import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import path from 'path'
import { answersAsBuilt } from '../webhook-server/decisions.js'
import { mergeOrder, enrichForOrder, mainStateFrom } from '../webhook-server/merge_order.js'

// Owner decision on PR #987 (2026-11-02): answers that only pick the built option, with no Note and no written answer,
// count as built and can merge with no reply. The same fixtures are read by lib/tests/test_owner_decisions.py, so the
// JS order logic and the Python scan are held to one answer per body. pr956/pr981 are the real PR bodies (names removed).
const dir = path.join(import.meta.dirname, 'fixtures', 'as_built')
const expected = JSON.parse(readFileSync(path.join(dir, 'expected.json'), 'utf8'))
const body = (f) => readFileSync(path.join(dir, f), 'utf8')

describe('answersAsBuilt', () => {
  for (const [file, want] of Object.entries(expected)) {
    it(`${file}: ${want ? 'counts as built' : 'still needs MARVIN'}`, () => expect(answersAsBuilt(body(file))).toBe(want))
  }
  it('junk never counts as built', () => {
    for (const b of [null, undefined, '', 42, '<!-- marvin:decisions -->']) expect(answersAsBuilt(b)).toBe(false)
  })
})

describe('the queue line follows it', () => {
  const url = (n) => `https://github.com/o/r/pull/${n}`
  const pr = (n, b) => ({ number: n, url: url(n), repo: 'o/r', body: b, baseRefName: 'main', headRefName: `b${n}`, headRefOid: 's', mergeable: 'MERGEABLE',
    statusCheckRollup: [{ __typename: 'CheckRun', name: 't', status: 'COMPLETED', conclusion: 'SUCCESS' }] })
  it('#956 (only the built answer) can merge even if the merge server still lists it; #981 (a Note) still waits', () => {
    const prs = enrichForOrder([pr(956, body('pr956.md')), pr(981, body('pr981.md'))], { repo: 'o/r', unbuilt: new Set([url(956), url(981)]) })
    const out = mergeOrder(prs, mainStateFrom(), { items: [{ url: url(956), approvedAt: 1 }, { url: url(981), approvedAt: 2 }] })
    expect(out.entries[url(956)].reason).toBe('queued · 1st · starts next')
    expect(out.entries[url(981)].reason).toBe("your answers aren't built yet")
    expect(out.next).toBe(url(956))
  })
})

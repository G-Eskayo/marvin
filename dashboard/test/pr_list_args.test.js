import { describe, it, expect } from 'vitest'
import { prListArgs, pendingChecksTtl } from '../electron/main/mr_repos.js'

describe('prListArgs: what each caller pays GitHub for', () => {
  it('the full listing asks for bodies, files and branch names (the MR list and merge-order check need them)', () => {
    const a = prListArgs('o/r')
    expect(a.slice(0, 5)).toEqual(['pr', 'list', '--repo', 'o/r', '--state'])
    expect(a[a.indexOf('--json') + 1]).toBe('number,title,url,body,files,baseRefName,headRefName,mergeable,statusCheckRollup')
  })
  it('the light listing (the status dot, polled every minute) asks for numbers only', () => {
    const a = prListArgs('o/r', { light: true })
    expect(a[a.indexOf('--json') + 1]).toBe('number,title,url')
    expect(a.join(' ')).not.toMatch(/files|body/)
  })
})

describe('pendingChecksTtl: a repo whose PRs have checks running is re-read soon, since finishing checks send no change ping', () => {
  const run = (status, conclusion = null) => ({ __typename: 'CheckRun', name: 'tests', status, conclusion })
  it('any PR with a running check or a pending status: a short re-read interval', () => {
    expect(pendingChecksTtl([{ statusCheckRollup: [run('COMPLETED', 'SUCCESS')] }, { statusCheckRollup: [run('IN_PROGRESS')] }])).toBeGreaterThan(0)
    expect(pendingChecksTtl([{ statusCheckRollup: [{ __typename: 'StatusContext', context: 'ci', state: 'PENDING' }] }])).toBeLessThanOrEqual(2 * 60_000)
  })
  it('settled checks, no checks, a light list without the field, or junk: no override', () => {
    expect(pendingChecksTtl([{ statusCheckRollup: [run('COMPLETED', 'SUCCESS')] }, { statusCheckRollup: [run('COMPLETED', 'FAILURE')] }])).toBeUndefined()
    expect(pendingChecksTtl([{ statusCheckRollup: [] }, { number: 1 }])).toBeUndefined()
    expect(pendingChecksTtl([])).toBeUndefined()
    expect(pendingChecksTtl(null)).toBeUndefined()
    expect(pendingChecksTtl([null])).toBeUndefined()
  })
})

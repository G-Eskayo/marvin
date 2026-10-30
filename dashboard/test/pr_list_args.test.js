import { describe, it, expect } from 'vitest'
import { prListArgs } from '../electron/main/mr_repos.js'

describe('prListArgs: what each caller pays GitHub for', () => {
  it('the full listing asks for bodies, files, branch names, labels and draft (MR list, merge order, grouping by project)', () => {
    const a = prListArgs('o/r')
    expect(a.slice(0, 5)).toEqual(['pr', 'list', '--repo', 'o/r', '--state'])
    expect(a[a.indexOf('--json') + 1]).toBe('number,title,url,body,files,baseRefName,headRefName,headRefOid,mergeable,statusCheckRollup,labels,isDraft')
  })
  it('the light listing (the status dot, polled every minute) asks for numbers only', () => {
    const a = prListArgs('o/r', { light: true })
    expect(a[a.indexOf('--json') + 1]).toBe('number,title,url')
    expect(a.join(' ')).not.toMatch(/files|body|labels|isDraft/)
  })
})

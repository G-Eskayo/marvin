import { describe, it, expect } from 'vitest'
import { prListArgs } from '../electron/main/mr_repos.js'

describe('prListArgs: what each caller pays GitHub for', () => {
  it('the full listing asks for bodies, files and branch names (the MR list and merge-order check need them)', () => {
    const a = prListArgs('o/r')
    expect(a.slice(0, 5)).toEqual(['pr', 'list', '--repo', 'o/r', '--state'])
    expect(a[a.indexOf('--json') + 1]).toBe('number,title,url,isDraft,body,files,baseRefName,headRefName,headRefOid,mergeable,statusCheckRollup')
  })
  it('the light listing (the status dot, polled every minute) asks for numbers only', () => {
    const a = prListArgs('o/r', { light: true })
    expect(a[a.indexOf('--json') + 1]).toBe('number,title,url')
    expect(a.join(' ')).not.toMatch(/files|body/)
  })
})

describe('the full listing carries isDraft, so merge order can skip drafts (clarity #227/#238 held #239, 2026-10-30)', () => {
  it('asks GitHub for isDraft', () => {
    const args = prListArgs('o/r')
    expect(args[args.indexOf('--json') + 1].split(',')).toContain('isDraft')
  })
})

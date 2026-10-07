import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { readMergeableRepos } from '../electron/main/profiles.js'

const withDir = (fn) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'profiles-'))
  try {
    return fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}
const put = (dir, name, obj) => writeFileSync(path.join(dir, name), typeof obj === 'string' ? obj : JSON.stringify(obj))

describe('readMergeableRepos', () => {
  it('lists only projects whose profile opts in to approving and denying from the dashboard', () =>
    withDir((dir) => {
      put(dir, 'a.json', { repo: 'o/a', merge_from_dashboard: true })
      put(dir, 'b.json', { repo: 'o/b', merge_from_dashboard: false })
      put(dir, 'c.json', { repo: 'o/c' })
      expect([...readMergeableRepos(dir)]).toEqual(['o/a'])
    }))

  it('opting in is separate from dispatching: a project with dispatch off can still be reviewed here', () =>
    withDir((dir) => {
      put(dir, 'a.json', { repo: 'o/a', dispatch: 'off', merge_from_dashboard: true })
      expect(readMergeableRepos(dir).has('o/a')).toBe(true)
    }))

  it('ignores broken files and a missing folder rather than failing the whole list', () =>
    withDir((dir) => {
      put(dir, 'bad.json', '{nope')
      put(dir, 'ok.json', { repo: 'o/ok', merge_from_dashboard: true })
      expect([...readMergeableRepos(dir)]).toEqual(['o/ok'])
      expect([...readMergeableRepos(path.join(dir, 'missing'))]).toEqual([])
    }))
})

import { listProfiles, setDispatch } from '../electron/main/profiles.js'
import { readFileSync } from 'fs'

describe('listProfiles', () => {
  it('summarises each project for the dashboard: name, dispatch, review opt-in, machines and checks', () =>
    withDir((dir) => {
      put(dir, 'cc.json', {
        repo: 'G-Eskayo/clarity-captions',
        dispatch: 'off',
        merge_from_dashboard: true,
        machines: ['mac-mini-1'],
        verify: [{ id: 'core', label: 'Core tests', required: true }, { id: 'app', label: 'App build', required: false, enabled: false }]
      })
      const [p] = listProfiles(dir)
      expect(p).toMatchObject({ repo: 'G-Eskayo/clarity-captions', name: 'clarity-captions', dispatch: 'off', mergeFromDashboard: true, machines: ['mac-mini-1'] })
      expect(p.checks).toEqual([{ label: 'Core tests', required: true, enabled: true }, { label: 'App build', required: false, enabled: false }])
    }))

  it('treats a profile with no dispatch field as off, and skips broken files', () =>
    withDir((dir) => {
      put(dir, 'a.json', { repo: 'o/a', verify: [] })
      put(dir, 'bad.json', '{nope')
      const list = listProfiles(dir)
      expect(list.map((p) => [p.repo, p.dispatch])).toEqual([['o/a', 'off']])
    }))
})

describe('setDispatch', () => {
  const text = '{\n  "_readme": "keep me",\n  "repo": "o/a",\n  "dispatch": "off",\n  "machines": ["m"]\n}\n'

  it('flips only the dispatch value, leaving the rest of the file exactly as it was', () =>
    withDir((dir) => {
      put(dir, 'a.json', text)
      setDispatch('o/a', 'on', dir)
      expect(readFileSync(path.join(dir, 'a.json'), 'utf-8')).toBe(text.replace('"dispatch": "off"', '"dispatch": "on"'))
      setDispatch('o/a', 'off', dir)
      expect(readFileSync(path.join(dir, 'a.json'), 'utf-8')).toBe(text)
    }))

  it('refuses a value other than on/off, an unknown project, and a profile with no dispatch line', () =>
    withDir((dir) => {
      put(dir, 'a.json', text)
      put(dir, 'b.json', '{ "repo": "o/b" }')
      expect(() => setDispatch('o/a', 'maybe', dir)).toThrow(/on or off/i)
      expect(() => setDispatch('o/zzz', 'on', dir)).toThrow(/no profile/i)
      expect(() => setDispatch('o/b', 'on', dir)).toThrow(/dispatch/i)
    }))
})

import { setMergeFromDashboard } from '../electron/main/profiles.js'

describe('setMergeFromDashboard', () => {
  const text = '{\n  "_readme": "keep me",\n  "repo": "o/a",\n  "merge_from_dashboard": false,\n  "machines": ["m"]\n}\n'

  it('flips only the merge_from_dashboard value, leaving the rest of the file exactly as it was', () =>
    withDir((dir) => {
      put(dir, 'a.json', text)
      setMergeFromDashboard('o/a', true, dir)
      expect(readFileSync(path.join(dir, 'a.json'), 'utf-8')).toBe(text.replace('"merge_from_dashboard": false', '"merge_from_dashboard": true'))
      setMergeFromDashboard('o/a', false, dir)
      expect(readFileSync(path.join(dir, 'a.json'), 'utf-8')).toBe(text)
    }))

  it('refuses a value other than true/false, an unknown project, and a profile with no merge_from_dashboard line', () =>
    withDir((dir) => {
      put(dir, 'a.json', text)
      put(dir, 'b.json', '{ "repo": "o/b" }')
      expect(() => setMergeFromDashboard('o/a', 'maybe', dir)).toThrow(/true or false/i)
      expect(() => setMergeFromDashboard('o/zzz', true, dir)).toThrow(/no profile/i)
      expect(() => setMergeFromDashboard('o/b', true, dir)).toThrow(/merge_from_dashboard/i)
    }))
})

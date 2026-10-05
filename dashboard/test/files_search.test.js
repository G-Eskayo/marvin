import { describe, it, expect, vi } from 'vitest'
import { searchFiles, isRevealable } from '../electron/main/files_search.js'

const HOME = '/Users/me'
const hit = (p, match = 'name') => ({ path: p, name: p.split('/').pop(), bucket: 'x', mtime: 1, size: 2, isDir: false, match })
const catalog = {
  projects: [
    { id: 'clarity-captions', name: 'Clarity Captions', localPaths: [`${HOME}/Developer/clarity-captions`, `${HOME}/Documents/Projects/clarity-captions`] },
    { id: 'marvin', name: 'marvin', localPaths: [`${HOME}/.agents`] },
    { id: 'portfolio-website-updater', name: 'Portfolio updater', localPaths: [`${HOME}/Documents/Projects/portfolio-website-updater`] }
  ]
}

describe('searchFiles', () => {
  it('runs the shared findit search and returns its two groups', async () => {
    const run = vi.fn(async () => JSON.stringify({ name: [hit(`${HOME}/Documents/Career/cv.pdf`)], content: [hit(`${HOME}/Documents/School/n.pdf`, 'content')] }))
    const out = await searchFiles('cv', { run, catalog: null, home: HOME })
    expect(run).toHaveBeenCalledWith('cv')
    expect(out.name[0].name).toBe('cv.pdf')
    expect(out.content[0].match).toBe('content')
  })

  it('attributes a file to the project whose folder contains it', async () => {
    const run = async () =>
      JSON.stringify({
        name: [hit(`${HOME}/Developer/clarity-captions/design/icon/x.svg`), hit(`${HOME}/Documents/Career/cv.pdf`)],
        content: [hit(`${HOME}/Documents/Projects/portfolio-website-updater/templates/a.html`, 'content')]
      })
    const out = await searchFiles('x', { run, catalog, home: HOME })
    expect(out.name[0].project).toEqual({ id: 'clarity-captions', name: 'Clarity Captions' })
    expect(out.name[1].project).toBeNull()
    expect(out.content[0].project.id).toBe('portfolio-website-updater')
  })

  it('does not attribute a sibling folder that merely shares a name prefix', async () => {
    const run = async () => JSON.stringify({ name: [hit(`${HOME}/Developer/clarity-captions-old/a.md`)], content: [] })
    expect((await searchFiles('a', { run, catalog, home: HOME })).name[0].project).toBeNull()
  })

  it('returns empty groups for a blank query without running anything', async () => {
    const run = vi.fn()
    expect(await searchFiles('  ', { run, catalog, home: HOME })).toEqual({ name: [], content: [] })
    expect(run).not.toHaveBeenCalled()
  })

  it('degrades to empty groups if the search fails or prints junk', async () => {
    expect(await searchFiles('a', { run: async () => { throw new Error('timeout') }, catalog, home: HOME })).toEqual({ name: [], content: [], error: 'timeout' })
    expect((await searchFiles('a', { run: async () => 'not json', catalog, home: HOME })).error).toBeTruthy()
  })
})

describe('isRevealable', () => {
  it('allows paths inside the searched folders only', () => {
    expect(isRevealable(`${HOME}/Documents/a.pdf`, HOME)).toBe(true)
    expect(isRevealable(`${HOME}/Developer/x/y.md`, HOME)).toBe(true)
    expect(isRevealable(`${HOME}/.ssh/id_rsa`, HOME)).toBe(false)
    expect(isRevealable('/etc/passwd', HOME)).toBe(false)
    expect(isRevealable(`${HOME}/Documents/../.ssh/id_rsa`, HOME)).toBe(false)
    expect(isRevealable('relative/path', HOME)).toBe(false)
    expect(isRevealable(`${HOME}/Documents`, HOME)).toBe(false)
  })
})

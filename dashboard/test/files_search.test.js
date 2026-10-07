import { describe, it, expect, vi } from 'vitest'
import { searchFiles, isRevealable, isLinkable, linkAction } from '../electron/main/files_search.js'

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

// 2026-10-07: Dropbox (and other cloud drives) were invisible to search, and the master map's links
// need to open things on the Mac without letting a link run a script or read a token file.
describe('cloud storage and map links', () => {
  it('a file in Dropbox is revealable (it is searched now)', () => {
    expect(isRevealable(`${HOME}/Library/CloudStorage/Dropbox/Gil/plan.pdf`, HOME)).toBe(true)
  })
  it('map links may open memory, handoffs and projects under ~/.claude and ~/.agents', () => {
    expect(isLinkable(`${HOME}/.claude/handoffs/h.md`, HOME)).toBe(true)
    expect(isLinkable(`${HOME}/.agents/docs/plans/p.md`, HOME)).toBe(true)
    expect(isLinkable(`${HOME}/Developer/nourished`, HOME)).toBe(true)
  })
  it('never a hidden file inside those roots, nor anything outside them, nor ..', () => {
    expect(isLinkable(`${HOME}/.claude/.gh-token`, HOME)).toBe(false)
    expect(isLinkable(`${HOME}/.ssh/id_ed25519`, HOME)).toBe(false)
    expect(isLinkable(`${HOME}/Developer/../.ssh/id_ed25519`, HOME)).toBe(false)
    expect(isLinkable('relative/path.md', HOME)).toBe(false)
  })
  it('folders and documents open; anything else is only shown in Finder, so a link never runs code', () => {
    expect(linkAction('/x/Developer/nourished', true)).toBe('open')
    expect(linkAction('/x/a/notes.md', false)).toBe('open')
    expect(linkAction('/x/a/Report.PDF', false)).toBe('open')
    expect(linkAction('/x/a/undo.sh', false)).toBe('reveal')
    expect(linkAction('/x/a/run.command', false)).toBe('reveal')
    expect(linkAction('/x/a/Tool.app', true)).toBe('reveal')
  })
})

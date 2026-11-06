// `marvin show` (G-Eskayo/marvin#715): what a request may name, where a shown file may live, which project's window
// it opens in. Real files in a throwaway folder; never the real HOME.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, symlinkSync, realpathSync, lstatSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { allowedRoots, checkShowPath, isTempPath, parseShowRequest, projectFor, viewKind, cleanRepoPath, UNSORTED } from '../electron/main/show.js'
import { buildContext, matchName } from '../electron/main/deliverables.js'

let home
beforeEach(() => {
  // A home that is NOT under a temp root as far as the checks are concerned: mkdtemp lands in /var/folders on macOS,
  // which is a temp root, so the test home is judged through injected roots and a realpath that maps it elsewhere.
  home = realpathSync(mkdtempSync(path.join(tmpdir(), 'show-home-')))
})
afterEach(() => rmSync(home, { recursive: true, force: true }))

const put = (rel, data = 'x') => {
  const full = path.join(home, rel)
  mkdirSync(path.dirname(full), { recursive: true })
  writeFileSync(full, data)
  return full
}
// The test home lives under the OS temp folder; present it as /Users/t so the temp rule judges paths as at home.
const FAKE = '/Users/t'
const realpath = (p) => {
  const r = realpathSync(p.startsWith(FAKE) ? path.join(home, p.slice(FAKE.length)) : p)
  return r.startsWith(home) ? FAKE + r.slice(home.length) : r
}
const stat = (p) => (p.startsWith(FAKE) ? lstatSync(path.join(home, p.slice(FAKE.length))) : lstatSync(p))
const check = (p, roots) => checkShowPath(p, { roots: roots || allowedRoots({ home: FAKE, projects: PROJECTS }), realpath, stat })

const PROJECTS = [
  { id: 'marvin', name: 'MARVIN', repo: 'G-Eskayo/marvin', status: 'active', localPaths: [`${FAKE}/.agents`] },
  { id: 'marvin-instance', name: 'MARVIN instance', repo: 'G-Eskayo/marvin-instance', status: 'active', localPaths: [`${FAKE}/.agents/instance`] },
  { id: 'portfolio-website-updater', name: 'Portfolio', repo: 'G-Eskayo/portfolio-website-updater', status: 'active', localPaths: [`${FAKE}/Developer/portfolio-website-updater`] },
  { id: 'portfolio-website', name: 'Portfolio_Website', repo: 'G-Eskayo/Portfolio_Website', status: 'archived', localPaths: [`${FAKE}/Developer/Portfolio_Website`] },
  { id: 'clarity-captions', name: 'Seal Speak', repo: 'G-Eskayo/clarity-captions', status: 'active', localPaths: [`${FAKE}/Developer/clarity-captions`] }
]

describe('checkShowPath: where a shown file may live', () => {
  it('shows a file in the outbox, in MARVIN, and in a project clone', () => {
    put('.claude/outbox/marvin-2026-11-02-x/a.png')
    put('.agents/instance/docs/plans/p.md')
    put('Developer/portfolio-website-updater/docs/x.md')
    for (const p of ['.claude/outbox/marvin-2026-11-02-x/a.png', '.agents/instance/docs/plans/p.md', 'Developer/portfolio-website-updater/docs/x.md']) {
      expect(check(`${FAKE}/${p}`).ok, p).toBe(true)
    }
  })

  it('refuses a path outside the allowed roots, however it is spelled', () => {
    put('.claude/.gh-token', 'ghp_secret')
    put('Desktop/private.png')
    expect(check(`${FAKE}/.claude/.gh-token`).ok).toBe(false)
    expect(check(`${FAKE}/Desktop/private.png`).reason).toMatch(/Outside/)
    expect(check(`${FAKE}/.claude/outbox/../.gh-token`).ok).toBe(false)
    expect(check('/etc/passwd').ok).toBe(false)
    expect(check('relative/path.png').reason).toMatch(/absolute/)
    expect(check('').ok).toBe(false)
    expect(check(`${FAKE}/.claude/outbox/a\0.png`).ok).toBe(false)
  })

  it('refuses a symlink inside an allowed root that points outside it', () => {
    const secret = put('Desktop/secret.txt', 'secret')
    mkdirSync(path.join(home, '.claude/outbox'), { recursive: true })
    symlinkSync(secret, path.join(home, '.claude/outbox/link.txt'))
    expect(check(`${FAKE}/.claude/outbox/link.txt`).ok).toBe(false)
  })

  it('refuses secrets even inside a project clone', () => {
    put('Developer/portfolio-website-updater/.env', 'KEY=1')
    put('Developer/portfolio-website-updater/deploy/server.pem')
    put('.agents/.ssh/id_ed25519')
    for (const p of ['Developer/portfolio-website-updater/.env', 'Developer/portfolio-website-updater/deploy/server.pem', '.agents/.ssh/id_ed25519']) {
      expect(check(`${FAKE}/${p}`).reason, p).toMatch(/secret/)
    }
  })

  it('refuses a temp path (the CLI copies it into the outbox first), a folder, and a missing file', () => {
    expect(isTempPath('/private/tmp/claude-501/x/scratchpad/shot.png')).toBe(true)
    expect(isTempPath('/tmp/x.png')).toBe(true)
    expect(isTempPath('/var/folders/ab/T/x.pdf')).toBe(true)
    expect(isTempPath('/tmpfoo/x.png')).toBe(false)
    mkdirSync(path.join(home, '.claude/outbox/dir'), { recursive: true })
    expect(check(`${FAKE}/.claude/outbox/dir`).reason).toMatch(/folder/)
    expect(check(`${FAKE}/.claude/outbox/gone.png`).reason).toMatch(/Not found/)
    // A real temp file, judged with the real realpath: refused with the reason that says what to do.
    const t = path.join(home, 'shot.png')
    writeFileSync(t, 'x')
    expect(checkShowPath(t, { roots: [home] }).reason).toMatch(/temp folder/)
  })
})

describe('parseShowRequest', () => {
  it('takes a file, a PR file and a web address', () => {
    expect(parseShowRequest({ kind: 'file', path: '/Users/t/a.png', project: 'marvin' }).req).toEqual({ kind: 'file', path: '/Users/t/a.png', project: 'marvin' })
    expect(parseShowRequest({ kind: 'pr', repo: 'G-Eskayo/marvin', number: 934, path: 'docs/design/m/index.html' }).req).toMatchObject({ kind: 'pr', number: 934, ref: null })
    expect(parseShowRequest({ kind: 'url', url: 'https://example.com/a' }).req.url).toBe('https://example.com/a')
  })
  it('refuses junk', () => {
    for (const b of [null, 'x', {}, { kind: 'file', path: 'rel.png' }, { kind: 'pr', repo: 'bad', number: 1, path: 'a' },
      { kind: 'pr', repo: 'o/r', number: 1, path: '../etc/passwd' }, { kind: 'pr', repo: 'o/r', number: -1, path: 'a' },
      { kind: 'pr', repo: 'o/r', path: 'a' }, { kind: 'pr', repo: 'o/r', ref: 'a b', path: 'a' },
      { kind: 'url', url: 'javascript:alert(1)' }, { kind: 'url', url: 'file:///etc/passwd' }, { kind: 'file', path: '/a', project: '../x' }]) {
      expect(parseShowRequest(b).ok, JSON.stringify(b)).toBe(false)
    }
  })
  it('cleanRepoPath refuses traversal, absolute and encoded paths', () => {
    expect(cleanRepoPath('docs/a.png')).toBe('docs/a.png')
    for (const p of ['/etc/passwd', '../a', 'a/../../b', 'a/%2e%2e/b', 'a\\b', 'https://x', '']) expect(cleanRepoPath(p), p).toBeNull()
  })
})

describe('projectFor: one window per project', () => {
  const ctx = buildContext({ projects: PROJECTS })
  const match = (name) => matchName(ctx, name, { top: false })
  const outboxRoot = `${FAKE}/.claude/outbox`

  it('an outbox item goes where the Docs tab puts it, even before the saved match map has it', () => {
    const view = { byProject: { 'clarity-captions': [{ path: 'seal-speak-share-139-2026-10-20' }] } }
    expect(projectFor({ kind: 'file' }, { real: `${outboxRoot}/seal-speak-share-139-2026-10-20/a.png`, outboxRoot, view, projects: PROJECTS }).id).toBe('clarity-captions')
    // The folder name marvin show writes: <project slug>-<date>-<topic>. The case from the ticket: before, this name
    // ("2026-11-02-portfolio-migration-screenshots") matched nothing.
    expect(projectFor({ kind: 'file' }, { real: `${outboxRoot}/portfolio-website-updater-2026-11-02-migration-screenshots/a.png`, outboxRoot, projects: PROJECTS, matchOutboxName: match }).id).toBe('portfolio-website-updater')
    expect(projectFor({ kind: 'file' }, { real: `${outboxRoot}/marvin-2026-11-02-show-window-mockup/a.png`, outboxRoot, projects: PROJECTS, matchOutboxName: match }).id).toBe('marvin')
  })

  it('a clone file goes to its project; the longest clone wins (instance inside ~/.agents)', () => {
    expect(projectFor({ kind: 'file' }, { real: `${FAKE}/.agents/instance/docs/plans/p.md`, projects: PROJECTS }).id).toBe('marvin-instance')
    expect(projectFor({ kind: 'file' }, { real: `${FAKE}/.agents/lib/x.py`, projects: PROJECTS }).id).toBe('marvin')
    // A sibling whose name starts the same is not inside it.
    expect(projectFor({ kind: 'file' }, { real: `${FAKE}/Developer/portfolio-website-updater2/x.md`, projects: PROJECTS }).id).toBe(UNSORTED.id)
  })

  it('a file the other Mac sent is filed by the project it named, not as MARVIN\'s for sitting in ~/.agents', () => {
    const real = `${FAKE}/.agents/var/show-inbox/1793-1/shot.png`
    const inboxRoot = `${FAKE}/.agents/var/show-inbox`
    expect(projectFor({ kind: 'file', project: 'clarity-captions' }, { real, inboxRoot, projects: PROJECTS }).id).toBe('clarity-captions')
    expect(projectFor({ kind: 'file', outboxName: 'portfolio-website-updater-2026-11-02-x' }, { real, inboxRoot, projects: PROJECTS, matchOutboxName: match }).id).toBe('portfolio-website-updater')
    expect(projectFor({ kind: 'file' }, { real, inboxRoot, projects: PROJECTS }).id).toBe(UNSORTED.id)
  })

  it('a PR file goes to its repo\'s project; a named project is the last resort; else Unsorted', () => {
    expect(projectFor({ kind: 'pr', repo: 'g-eskayo/clarity-captions' }, { projects: PROJECTS }).id).toBe('clarity-captions')
    expect(projectFor({ kind: 'url', project: 'marvin' }, { projects: PROJECTS }).id).toBe('marvin')
    expect(projectFor({ kind: 'url', project: 'nope' }, { projects: PROJECTS }).id).toBe(UNSORTED.id)
  })
})

describe('viewKind', () => {
  it('HTML runs in the frame; everything else goes through the Docs viewer', () => {
    expect(viewKind('index.html')).toBe('html')
    expect(viewKind('a.png')).toBe('image')
    expect(viewKind('a.md')).toBe('markdown')
    expect(viewKind('a.pdf')).toBe('pdf')
  })
})

import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, symlinkSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createDocsService } from '../electron/main/docs_service.js'

// #539: a doc's images resolve against the doc's own folder (as GitHub does), read from the local clone when there is
// one, else through the signed-in image loader (private repos 404 for a plain <img>).
const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0])
const rec = (over) => ({ id: 'p1', name: 'P', kind: 'repo', repo: 'acme/p-one', status: 'active', localPaths: [], docs: {}, tags: [], summary_md: '# P\n', ...over })
const cat = (...projects) => ({ generated_at: 'x', projects })
const withClone = async (fn) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'docimg-'))
  try {
    mkdirSync(path.join(dir, 'docs', 'plans'), { recursive: true })
    mkdirSync(path.join(dir, 'docs', 'screenshots'), { recursive: true })
    writeFileSync(path.join(dir, 'docs', 'screenshots', 'a.png'), PNG)
    writeFileSync(path.join(dir, 'docs', 'plans', 'shot one.png'), PNG)
    writeFileSync(path.join(dir, 'docs', 'diagrams.png'), PNG)
    writeFileSync(path.join(dir, 'docs', 'plans', 'notes.txt'), 'not an image')
    return await fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}
const svc = (c, extra = {}) => createDocsService({ getCatalog: () => c, exec: vi.fn(), readMaster: () => null, ...extra })

describe('docs images (#539)', () => {
  it('resolves ../ against the doc\'s own folder and reads the local clone', () =>
    withClone(async (dir) => {
      const r = await svc(cat(rec({ localPaths: [dir] }))).image('p1', 'docs/plans/plan.md', '../screenshots/a.png')
      expect(r.ok).toBe(true)
      expect(r.dataUrl).toMatch(/^data:image\/png;base64,/)
    }))

  it('handles ./, URL-encoded names and spaces beside the doc', () =>
    withClone(async (dir) => {
      const s = svc(cat(rec({ localPaths: [dir] })))
      expect((await s.image('p1', 'docs/plans/plan.md', './shot%20one.png')).ok).toBe(true)
      expect((await s.image('p1', 'docs/plans/plan.md', 'shot one.png')).ok).toBe(true)
    }))

  it('a leading / means the repo root, and a path not found beside the doc falls back to the repo root', () =>
    withClone(async (dir) => {
      const s = svc(cat(rec({ localPaths: [dir] })))
      expect((await s.image('p1', 'docs/plans/plan.md', '/docs/diagrams.png')).ok).toBe(true)
      expect((await s.image('p1', 'docs/plans/plan.md', 'docs/diagrams.png')).ok).toBe(true) // older repo-root form
    }))

  it('never reads outside the repo, and refuses non-images', () =>
    withClone(async (dir) => {
      const s = svc(cat(rec({ localPaths: [dir] })))
      for (const bad of ['../../../../etc/hosts', '../../..', '/../../etc/hosts', '%2e%2e/%2e%2e/%2e%2e/etc/hosts']) {
        const r = await s.image('p1', 'docs/plans/plan.md', bad)
        expect(r.ok).toBe(false)
      }
      expect(await s.image('p1', 'docs/plans/plan.md', 'notes.txt')).toMatchObject({ ok: false, reason: 'not an image' })
      expect(await s.image('p1', 'docs/plans/plan.md', 'missing.png')).toMatchObject({ ok: false })
    }))

  it('does not follow a symlink out of the repo', () =>
    withClone(async (dir) => {
      const outside = mkdtempSync(path.join(tmpdir(), 'docimg-out-'))
      try {
        writeFileSync(path.join(outside, 'secret.png'), PNG)
        symlinkSync(path.join(outside, 'secret.png'), path.join(dir, 'docs', 'plans', 'link.png'))
        expect((await svc(cat(rec({ localPaths: [dir] }))).image('p1', 'docs/plans/plan.md', 'link.png')).ok).toBe(false)
      } finally {
        rmSync(outside, { recursive: true, force: true })
      }
    }))

  it('a GitHub-only project loads through the signed-in loader, at the doc-relative path', async () => {
    const loadRemoteImage = vi.fn(async () => ({ ok: true, dataUrl: 'data:image/png;base64,AA' }))
    const r = await svc(cat(rec()), { loadRemoteImage }).image('p1', 'docs/plans/plan.md', '../screenshots/a%20b.png')
    expect(r.ok).toBe(true)
    expect(loadRemoteImage).toHaveBeenCalledWith('https://raw.githubusercontent.com/acme/p-one/HEAD/docs/screenshots/a%20b.png')
  })

  it('a remote failure falls back to the repo-root path, then says why', async () => {
    const loadRemoteImage = vi.fn(async () => ({ ok: false, reason: 'not found (404)' }))
    const r = await svc(cat(rec()), { loadRemoteImage }).image('p1', 'docs/plans/plan.md', 'docs/x.png')
    expect(loadRemoteImage).toHaveBeenCalledTimes(2)
    expect(r).toMatchObject({ ok: false, reason: 'not found (404)' })
  })

  it('absolute URLs and data: are left to the page', async () => {
    const s = svc(cat(rec()))
    expect((await s.image('p1', 'a.md', 'https://x.test/a.png')).ok).toBe(false)
    expect((await s.image('p1', 'a.md', 'data:image/png;base64,AA')).ok).toBe(false)
  })

  it('an unknown project or a project with no copy anywhere says so', async () => {
    expect((await svc(cat()).image('nope', 'a.md', 'a.png')).ok).toBe(false)
    expect((await svc(cat(rec({ repo: null, kind: 'local' }))).image('p1', 'a.md', 'a.png')).ok).toBe(false)
  })
})

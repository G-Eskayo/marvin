// #570: downscaled, cached covers (thumbs.js). Temp HOME only; the resize is a counting fake.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, readdirSync, utimesSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createThumbs, THUMB_WIDTH } from '../electron/main/thumbs.js'

const PNG = Buffer.from('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082', 'hex')
let home, prev, root, resizes
const resize = (buf, w) => (resizes.push(w), Buffer.from('fake-jpeg'))
beforeEach(() => {
  prev = process.env.HOME
  home = mkdtempSync(path.join(tmpdir(), 'thumbs-'))
  process.env.HOME = home
  root = path.join(home, '.claude', 'outbox')
  mkdirSync(path.join(root, 'f'), { recursive: true })
  writeFileSync(path.join(root, 'f', 'a.png'), PNG)
  resizes = []
})
afterEach(() => {
  process.env.HOME = prev
  rmSync(home, { recursive: true, force: true })
})

describe('thumbs', () => {
  it('makes a small JPEG once, under ~/.agents/var/thumbs, then reads it from disk', () => {
    const t = createThumbs({ resize })
    const a = t.thumb('f/a.png')
    expect(a).toEqual({ ok: true, dataUrl: `data:image/jpeg;base64,${Buffer.from('fake-jpeg').toString('base64')}` })
    expect(resizes).toEqual([THUMB_WIDTH])
    expect(readdirSync(path.join(home, '.agents', 'var', 'thumbs')).length).toBe(1)
    expect(createThumbs({ resize }).thumb('f/a.png')).toEqual(a) // a new process: from disk
    expect(resizes.length).toBe(1)
  })
  it('a changed image gets a new thumb', () => {
    const t = createThumbs({ resize })
    t.thumb('f/a.png')
    const later = new Date(Date.now() + 10_000)
    utimesSync(path.join(root, 'f', 'a.png'), later, later)
    t.thumb('f/a.png')
    expect(resizes.length).toBe(2)
  })
  it('refuses traversal, absolute paths, folders, non-images, and never throws', () => {
    const t = createThumbs({ resize })
    writeFileSync(path.join(root, 'f', 'fake.png'), 'not a png')
    for (const p of ['../../etc/passwd', '/etc/passwd', 'f', 'f/fake.png', 'missing.png', null]) expect(t.thumb(p).ok).toBe(false)
    expect(resizes.length).toBe(0)
  })
  it('a resize that fails is a plain reason, not a crash', () => {
    expect(createThumbs({ resize: () => null }).thumb('f/a.png')).toEqual({ ok: false, reason: 'could not be drawn' })
    expect(createThumbs({ resize: () => { throw new Error('boom') } }).thumb('f/a.png').ok).toBe(false)
  })
  it('an SVG is passed through as is', () => {
    writeFileSync(path.join(root, 'f', 'x.svg'), '<svg xmlns="http://www.w3.org/2000/svg"/>')
    expect(createThumbs({ resize }).thumb('f/x.svg').dataUrl.startsWith('data:image/svg+xml;base64,')).toBe(true)
  })
  it('prunes to the newest 2000 once past 3000 files (bounded space)', () => {
    const dir = path.join(home, 'tdir')
    mkdirSync(dir)
    for (let i = 0; i < 3001; i++) writeFileSync(path.join(dir, `${i}.jpg`), 'x')
    createThumbs({ resize, dir }).prune()
    expect(readdirSync(dir).length).toBe(2000)
    expect(existsSync(path.join(home, '.agents', 'var', 'thumbs'))).toBe(false)
  })
})

import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, rmSync, readdirSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { parsePrImages, resolvePrImageUrl, createImageLoader } from '../electron/main/pr_images.js'

const CTX = { repo: 'G-Eskayo/clarity-captions', headRef: 'design/v1-polish-mocks' }
const RAW = 'https://raw.githubusercontent.com/G-Eskayo/clarity-captions/design/v1-polish-mocks'

// The shape of clarity-captions #96, the PR that showed no images in the dashboard (2026-10-09).
const MOCKS_BODY = `Mock-ups of the owner's v1 polish spec, for approval.

## 1 · Main screen while captioning
Gear top-left (icon only, theme-colored), small Stop circle at the top middle.
![Main screen](${RAW}/docs/design/mocks/2026-10-09/01-main-captioning.png)

## 2 · Paused (after pressing X)
Start captions top-middle, captions dimmed, SAVE then NEW stacked under Start.
![Paused](${RAW}/docs/design/mocks/2026-10-09/02-paused-save-new.png)

## Open questions
- [ ] Button style: A, B or C?`

describe('parsePrImages: every image in a PR description, in order', () => {
  it('finds each mock-up with its section heading as the group and the line above as its caption', () => {
    const images = parsePrImages(MOCKS_BODY, CTX)
    expect(images).toEqual([
      { url: `${RAW}/docs/design/mocks/2026-10-09/01-main-captioning.png`, alt: 'Main screen', group: '1 · Main screen while captioning', caption: 'Gear top-left (icon only, theme-colored), small Stop circle at the top middle.' },
      { url: `${RAW}/docs/design/mocks/2026-10-09/02-paused-save-new.png`, alt: 'Paused', group: '2 · Paused (after pressing X)', caption: 'Start captions top-middle, captions dimmed, SAVE then NEW stacked under Start.' }
    ])
  })

  it('reads HTML <img> tags too, with any attribute order and quoting', () => {
    const body = `## Frames\n<img width="300" alt='Option A' src="https://github.com/user-attachments/assets/abc-123">\n<img src=https://x.githubusercontent.com/a.gif alt=Clip>`
    const images = parsePrImages(body, CTX)
    expect(images.map((i) => [i.url, i.alt, i.group])).toEqual([
      ['https://github.com/user-attachments/assets/abc-123', 'Option A', 'Frames'],
      ['https://x.githubusercontent.com/a.gif', 'Clip', 'Frames']
    ])
  })

  it('keeps several images on one line in left-to-right order, mixing both syntaxes', () => {
    const body = `<img src="${RAW}/b.png"> then ![a](${RAW}/a.png "Title A") and ![c](${RAW}/c.png)`
    expect(parsePrImages(body, CTX).map((i) => i.url)).toEqual([`${RAW}/b.png`, `${RAW}/a.png`, `${RAW}/c.png`])
  })

  it('uses text on the image line itself as the caption before anything above it', () => {
    const body = `Above the image.\n- **Light:** ![l](${RAW}/l.png) light mode`
    expect(parsePrImages(body, CTX)[0].caption).toBe('Light: light mode')
  })

  it('falls back to the title, then the alt text, when there is no text to use', () => {
    expect(parsePrImages(`## H\n![alt only](${RAW}/x.png "The title")`, CTX)[0].caption).toBe('The title')
    expect(parsePrImages(`![alt only](${RAW}/y.png)`, CTX)[0].caption).toBe('alt only')
  })

  it('a heading resets the caption, so the previous section\'s text never labels the next image', () => {
    const body = `## One\nNote for one.\n![a](${RAW}/a.png)\n## Two\n![b](${RAW}/b.png)`
    expect(parsePrImages(body, CTX)[1]).toMatchObject({ group: 'Two', caption: 'b' })
  })

  it('points a repo-relative path at the PR\'s own branch', () => {
    const images = parsePrImages('![s](docs/images/pr/83-settings.png) ![t](./design/t.png) ![u](/abs/u.png)', CTX)
    expect(images.map((i) => i.url)).toEqual([
      `${RAW}/docs/images/pr/83-settings.png`,
      `${RAW}/design/t.png`,
      `${RAW}/abs/u.png`
    ])
  })

  it('shows a repeated image once', () => {
    expect(parsePrImages(`![a](${RAW}/a.png)\n![again](${RAW}/a.png)`, CTX)).toHaveLength(1)
  })

  it('ignores images inside code fences: they are examples, not evidence', () => {
    const body = '```md\n![x](https://raw.githubusercontent.com/o/r/b/x.png)\n```\n![y](https://raw.githubusercontent.com/o/r/b/y.png)'
    expect(parsePrImages(body, CTX).map((i) => i.alt)).toEqual(['y'])
  })

  it('drops unsafe or unresolvable sources rather than guessing', () => {
    const body = `![js](javascript:alert(1)) ![f](file:///etc/passwd) ![p](//evil.com/x.png) ![up](../secrets.png) ![e]()`
    expect(parsePrImages(body, CTX)).toEqual([])
    expect(parsePrImages('![rel](a.png)', { repo: 'o/r' })).toEqual([]) // no branch known: can't resolve
  })

  it('survives non-strings, malformed markdown and a huge body', () => {
    expect(parsePrImages(null, CTX)).toEqual([])
    expect(parsePrImages(42, CTX)).toEqual([])
    expect(parsePrImages('![broken](no close paren\n![ok](https://raw.githubusercontent.com/o/r/b/ok.png)', CTX).map((i) => i.alt)).toEqual(['ok'])
    const huge = 'word '.repeat(300_000) + `\n![late](${RAW}/late.png)`
    const start = Date.now()
    expect(parsePrImages(huge, CTX)).toEqual([]) // beyond the parse limit
    expect(Date.now() - start).toBeLessThan(2000)
    const many = Array.from({ length: 100 }, (_, i) => `![${i}](${RAW}/${i}.png)`).join('\n')
    expect(parsePrImages(many, CTX)).toHaveLength(60)
  })

  it('resolvePrImageUrl keeps data: images and absolute URLs as given', () => {
    expect(resolvePrImageUrl('data:image/png;base64,AA', CTX)).toBe('data:image/png;base64,AA')
    expect(resolvePrImageUrl('https://example.com/x.png', CTX)).toBe('https://example.com/x.png')
  })
})

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3])
const GIF = Buffer.from('GIF89a....', 'ascii')
function response(bytes, { status = 200, length } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (h) => (h.toLowerCase() === 'content-length' && length !== undefined ? String(length) : null) },
    arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
  }
}

describe('createImageLoader: bytes fetched in the main process, handed over as data: URLs', () => {
  it('returns a data: URL with the sniffed type, so GIFs stay GIFs and animate', async () => {
    const loader = createImageLoader({ fetchFn: vi.fn().mockResolvedValue(response(GIF)), token: () => '' })
    const r = await loader.load('https://raw.githubusercontent.com/o/r/b/clip.gif')
    expect(r.ok).toBe(true)
    expect(r.dataUrl.startsWith('data:image/gif;base64,')).toBe(true)
  })

  it('sends the GitHub credential to GitHub hosts only, so private repos load and the token goes nowhere else', async () => {
    const fetchFn = vi.fn().mockResolvedValue(response(PNG))
    const loader = createImageLoader({ fetchFn, token: () => 'SECRET' })
    await loader.load('https://raw.githubusercontent.com/G-Eskayo/finance-os/main/x.png')
    await loader.load('https://x.githubusercontent.com/y.png')
    expect(fetchFn.mock.calls[0][1].headers.Authorization).toBe('token SECRET')
    expect(fetchFn.mock.calls[1][1].headers.Authorization).toBeUndefined()
  })

  it('refuses hosts outside GitHub and non-https, without fetching', async () => {
    const fetchFn = vi.fn()
    const loader = createImageLoader({ fetchFn, token: () => 'SECRET' })
    expect(await loader.load('https://evil.example/x.png')).toMatchObject({ ok: false, reason: expect.stringContaining('evil.example') })
    expect(await loader.load('http://raw.githubusercontent.com/o/r/b/x.png')).toMatchObject({ ok: false })
    expect(await loader.load('not a url')).toMatchObject({ ok: false })
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('says why a private or missing image did not load', async () => {
    const loader = createImageLoader({ fetchFn: vi.fn().mockResolvedValue(response(Buffer.alloc(0), { status: 404 })) })
    expect(await loader.load('https://raw.githubusercontent.com/o/private/b/x.png')).toMatchObject({ ok: false, reason: expect.stringMatching(/not found \(404\)/) })
  })

  it('times out a hung request instead of spinning forever', async () => {
    const fetchFn = vi.fn((url, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))))
    const loader = createImageLoader({ fetchFn, timeoutMs: 30 })
    expect(await loader.load('https://raw.githubusercontent.com/o/r/b/slow.png')).toEqual({ ok: false, reason: 'timed out' })
  })

  it('refuses an oversize image by its declared length or its real size', async () => {
    const declared = createImageLoader({ fetchFn: vi.fn().mockResolvedValue(response(PNG, { length: 99_000_000 })), maxBytes: 1000 })
    expect(await declared.load('https://raw.githubusercontent.com/o/r/b/big.png')).toMatchObject({ ok: false, reason: expect.stringMatching(/too large/) })
    const actual = createImageLoader({ fetchFn: vi.fn().mockResolvedValue(response(Buffer.concat([PNG, Buffer.alloc(5000)]))), maxBytes: 1000 })
    expect(await actual.load('https://raw.githubusercontent.com/o/r/b/big2.png')).toMatchObject({ ok: false, reason: expect.stringMatching(/too large/) })
  })

  it('refuses something that is not an image (an HTML error page served as 200)', async () => {
    const loader = createImageLoader({ fetchFn: vi.fn().mockResolvedValue(response(Buffer.from('<html>login</html>'))) })
    expect(await loader.load('https://raw.githubusercontent.com/o/r/b/x')).toEqual({ ok: false, reason: 'not an image' })
  })

  it('reports a network error in plain words', async () => {
    const loader = createImageLoader({ fetchFn: vi.fn().mockRejectedValue(new Error('ENOTFOUND')) })
    expect(await loader.load('https://raw.githubusercontent.com/o/r/b/x.png')).toMatchObject({ ok: false, reason: expect.stringContaining('ENOTFOUND') })
  })

  it('serves a repeat from memory, and concurrent asks share one fetch', async () => {
    const fetchFn = vi.fn().mockResolvedValue(response(PNG))
    const loader = createImageLoader({ fetchFn })
    const url = 'https://raw.githubusercontent.com/o/r/b/x.png'
    const [a, b] = await Promise.all([loader.load(url), loader.load(url)])
    await loader.load(url)
    expect(a).toEqual(b)
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })

  it('does not cache a failure, so a later retry can succeed', async () => {
    const fetchFn = vi.fn().mockResolvedValueOnce(response(Buffer.alloc(0), { status: 500 })).mockResolvedValueOnce(response(PNG))
    const loader = createImageLoader({ fetchFn })
    const url = 'https://raw.githubusercontent.com/o/r/b/x.png'
    expect((await loader.load(url)).ok).toBe(false)
    expect((await loader.load(url)).ok).toBe(true)
  })

  it('keeps a disk cache across loaders (app restarts) and refetches a corrupt entry', async () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'pr-images-'))
    try {
      const url = 'https://raw.githubusercontent.com/o/r/b/x.png'
      const first = vi.fn().mockResolvedValue(response(PNG))
      await createImageLoader({ fetchFn: first, cacheDir: dir }).load(url)
      const second = vi.fn()
      expect((await createImageLoader({ fetchFn: second, cacheDir: dir }).load(url)).ok).toBe(true)
      expect(second).not.toHaveBeenCalled()
      for (const f of readdirSync(dir)) writeFileSync(path.join(dir, f), '{not json')
      const third = vi.fn().mockResolvedValue(response(PNG))
      expect((await createImageLoader({ fetchFn: third, cacheDir: dir }).load(url)).ok).toBe(true)
      expect(third).toHaveBeenCalledTimes(1)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

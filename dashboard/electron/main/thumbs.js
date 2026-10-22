import { createHash } from 'crypto'
import { readFileSync, writeFileSync, mkdirSync, lstatSync, readdirSync, statSync, rmSync, renameSync } from 'fs'
import path from 'path'
import { resolveOutboxPath, MAX_IMAGE_BYTES } from './outbox.js'
import { sniffMime } from './pr_images.js'
import { varPath } from './marvin_paths.js'

// Downscaled covers for the Docs tab's deliverable cards and search hits (#570 speed budget): a card shows a 360 px
// JPEG instead of the full image (a 770 KB full-page screenshot is ~25 KB as a thumbnail). Made once per (path,
// mtime, size), saved under ~/.agents/var/thumbs (MARVIN-owned), then read from disk. Every path goes through the
// outbox guard. `resize(buffer, width)` -> JPEG bytes is injected: Electron's nativeImage in the app, a fake in tests.
//
// Space: one small file per image viewed as a card, pruned to the newest KEEP when it passes MAX (bounded).
// Time: a cached thumb is one small read; a new one is one read + one resize.
export const THUMB_WIDTH = 360
const MAX = 3000
const KEEP = 2000

export function createThumbs({ resize, dir = null }) {
  const thumbsDir = () => dir || varPath('thumbs')
  let writes = 0

  function prune() {
    try {
      const files = readdirSync(thumbsDir()).filter((n) => n.endsWith('.jpg'))
      if (files.length <= MAX) return
      const aged = files.map((n) => ({ n, t: statSync(path.join(thumbsDir(), n)).mtimeMs })).sort((a, b) => b.t - a.t)
      for (const { n } of aged.slice(KEEP)) rmSync(path.join(thumbsDir(), n), { force: true })
    } catch {
      // pruning is best effort
    }
  }

  // { ok: true, dataUrl } or { ok: false, reason }. Never throws.
  function thumb(relPath) {
    try {
      const full = resolveOutboxPath(String(relPath))
      const st = lstatSync(full)
      if (!st.isFile()) return { ok: false, reason: 'not a file' }
      if (st.size > MAX_IMAGE_BYTES) return { ok: false, reason: 'too large' }
      const key = createHash('sha1').update(`${relPath}|${st.mtimeMs}|${st.size}|${THUMB_WIDTH}`).digest('hex')
      const file = path.join(thumbsDir(), `${key}.jpg`)
      try {
        return { ok: true, dataUrl: `data:image/jpeg;base64,${readFileSync(file).toString('base64')}` }
      } catch {
        // not made yet
      }
      const buf = readFileSync(full)
      const mime = sniffMime(buf)
      if (!mime || !mime.startsWith('image/') || mime === 'image/svg+xml') {
        // SVGs (and anything not a raster image) are not thumbnailed: an SVG is small and drawn as is
        if (/\.svg$/i.test(relPath) && !buf.includes(0)) return { ok: true, dataUrl: `data:image/svg+xml;base64,${buf.toString('base64')}` }
        return { ok: false, reason: 'not an image' }
      }
      const jpg = resize(buf, THUMB_WIDTH)
      if (!jpg || !jpg.length) return { ok: false, reason: 'could not be drawn' }
      try {
        mkdirSync(thumbsDir(), { recursive: true })
        writeFileSync(`${file}.tmp`, jpg)
        renameSync(`${file}.tmp`, file)
        if (++writes % 100 === 0) prune()
      } catch {
        // unwritable: still return the thumb
      }
      return { ok: true, dataUrl: `data:image/jpeg;base64,${Buffer.from(jpg).toString('base64')}` }
    } catch (err) {
      return { ok: false, reason: String(err?.message || err) }
    }
  }

  return { thumb, prune }
}

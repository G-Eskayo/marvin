// The Files tab's reader (G-Eskayo/marvin#89, #402): a read-only view of ~/.claude/outbox. Every file comes back in the
// form the renderer can show best: images as data: URLs read as bytes (the CSP allows img-src data:, same as
// portfolio.js), PDFs as their bytes for the renderer's own pdf.js view (PdfView), text kinds as text, and anything else (or too large, or unreadable) as a card: name, kind, size, reason. Never raw
// bytes decoded as UTF-8. Every path, including images a markdown file embeds, goes through resolveOutboxPath.
import { readFileSync, readdirSync, lstatSync, existsSync, realpathSync, openSync, readSync, closeSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { fileKind } from '../../src/lib/file_kinds.js'
import { sniffMime } from './pr_images.js'

// Resolved on every call (not at import), so a test's temp HOME is honoured and nothing touches the real ~/.claude.
export const outboxRoot = () => path.join(homedir(), '.claude', 'outbox')
export const MAX_TEXT_BYTES = 2 * 1024 * 1024 // 2 MB
export const MAX_IMAGE_BYTES = 15 * 1024 * 1024 // same cap as PR images (pr_images.js)
export const MAX_PDF_BYTES = 50 * 1024 * 1024 // sent over IPC once; pdf.js renders pages lazily from it
const MAX_DEPTH = 8

export function resolveOutboxPath(relPath) {
  if (typeof relPath !== 'string') throw new Error('Path must be a string')
  if (path.isAbsolute(relPath)) throw new Error('Absolute paths not allowed')
  const normalized = path.posix.normalize(relPath)
  if (normalized.split('/').includes('..')) throw new Error('Traversal (..) not allowed')

  const root = outboxRoot()
  const fullPath = path.join(root, normalized)
  let realFull, realRoot
  try {
    realFull = realpathSync(fullPath)
    realRoot = realpathSync(root)
  } catch {
    // Missing file: validate the intent only; the caller's stat reports "not found".
    if (!fullPath.startsWith(root + path.sep)) throw new Error('Path escapes outbox root')
    return fullPath
  }
  if (!realFull.startsWith(realRoot + path.sep) && realFull !== realRoot) throw new Error('Path escapes outbox root')
  return fullPath
}

// The real file type from its bytes, for images: a text file named .png is not an image.
function imageMime(buf, name) {
  const sniffed = sniffMime(buf) // no name passed: never guess from the extension
  if (sniffed && sniffed.startsWith('image/')) return sniffed
  if (/\.svg$/i.test(name) && !buf.includes(0)) {
    const head = buf.subarray(0, 4096).toString('utf8')
    if (/<svg[\s>]/i.test(head)) return 'image/svg+xml'
  }
  return null
}

const isPdf = (buf) => buf.length >= 5 && buf.subarray(0, 5).toString('latin1') === '%PDF-'

const mb = (n) => `${(n / 1048576).toFixed(n < 10 * 1048576 ? 1 : 0)} MB`

// A regular file inside the outbox, or a thrown plain reason.
function statFile(relPath) {
  const fullPath = resolveOutboxPath(relPath)
  let stat
  try {
    stat = lstatSync(fullPath)
  } catch {
    throw new Error(`File not found: ${relPath}`)
  }
  if (!stat.isFile()) throw new Error(`Not a regular file: ${relPath}`)
  return { fullPath, size: stat.size }
}

export function readOutboxFile(relPath) {
  const { fullPath, size } = statFile(relPath)
  const name = path.basename(relPath)
  const { kind, label } = fileKind(name)
  const base = { name, path: relPath, label, size }
  const card = (reason) => ({ ...base, kind: 'other', reason })

  const cap = kind === 'image' ? MAX_IMAGE_BYTES : kind === 'pdf' ? MAX_PDF_BYTES : MAX_TEXT_BYTES
  if (size > cap) return card(`Too large to show here (${mb(size)}; the limit is ${mb(cap)}).`)

  let buf
  try {
    buf = readFileSync(fullPath)
  } catch (err) {
    return card(`This file can't be read (${err.code === 'EACCES' || err.code === 'EPERM' ? 'permission denied' : err.code || err.message}).`)
  }

  if (kind === 'image') {
    const mime = imageMime(buf, name)
    if (!mime) return card(`Not a valid image: the contents don't match .${name.split('.').pop()}.`)
    return { ...base, kind, mime, dataUrl: `data:${mime};base64,${buf.toString('base64')}` }
  }
  if (kind === 'pdf') {
    if (!isPdf(buf)) return card('Not a valid PDF: the contents don\'t start like a PDF.')
    // The bytes arrive in the renderer as a Uint8Array; pdf.js there decides if the inside is readable (card if not).
    return { ...base, kind, data: buf }
  }
  // Everything else is shown as text, so it must be text: a NUL byte means binary.
  if (buf.includes(0)) return card(kind === 'other' ? 'No preview for this kind of file.' : 'This looks like a binary file, so there is no text to show.')
  const content = buf.toString('utf8')
  if (kind === 'json') {
    try {
      JSON.parse(content)
      return { ...base, kind: 'json', content }
    } catch {
      return { ...base, kind: 'text', content }
    }
  }
  return { ...base, kind: kind === 'other' ? 'text' : kind, content }
}

// An image a markdown file embeds (`shots/x.png`), resolved against that file's own folder. Read-only, images only,
// never outside the outbox: the joined path goes through the same guard as everything else. Remote and data: images
// are left to the page.
export function readOutboxImage(fromRel, src) {
  const no = (reason) => ({ ok: false, reason })
  if (typeof src !== 'string' || !src.trim()) return no('no image path')
  if (/^([a-z][a-z0-9+.-]*:|\/\/)/i.test(src)) return no('not an outbox image')
  if (src.startsWith('/')) return no('absolute paths are not allowed')
  let clean
  try {
    clean = decodeURIComponent(src.split(/[?#]/)[0])
  } catch {
    return no('bad image path')
  }
  if (typeof fromRel !== 'string') return no('no file')
  const joined = path.posix.normalize(path.posix.join(path.posix.dirname(fromRel), clean))
  if (joined === '..' || joined.startsWith('../') || path.isAbsolute(joined)) return no('outside the outbox')
  try {
    resolveOutboxPath(fromRel)
    const { fullPath, size } = statFile(joined)
    if (size > MAX_IMAGE_BYTES) return no(`too large (${mb(size)})`)
    const buf = readFileSync(fullPath)
    const mime = imageMime(buf, joined)
    if (!mime) return no('not an image')
    return { ok: true, mime, dataUrl: `data:${mime};base64,${buf.toString('base64')}` }
  } catch (err) {
    return no(String(err?.message || err))
  }
}

// The full path of an outbox file for Reveal in Finder / Open in Preview; throws for anything outside the outbox or missing.
export function outboxRevealPath(relPath) {
  return statFile(relPath).fullPath
}

// Open in Preview is only for PDFs: opening an arbitrary outbox file with its default app could run it (a .command,
// an .app, a script), so everything else stays Reveal in Finder only.
export function outboxOpenPath(relPath) {
  if (fileKind(relPath).kind !== 'pdf') throw new Error('Only PDFs open from here')
  return statFile(relPath).fullPath
}

// ── Deliverables in the Docs tab (#570) ─────────────────────────────────────────────────────────────────────────────
// The Docs tab shows outbox items under the project they're matched to (deliverables.js). These read the outbox one
// folder at a time, behind the same guard, never recursively on a click.

export const DIR_LIMIT = 200 // a folder lists its first 200 entries, then "N more" (marvin-icon-proto has 5,659 files)
const WALK_LIMIT = 10000

// One folder's entries, folders first, each with its kind label; `more` counts what was left out. Dot files are hidden.
export function listOutboxDir(relPath = '', limit = DIR_LIMIT) {
  const full = relPath ? resolveOutboxPath(relPath) : outboxRoot()
  let entries
  try {
    entries = readdirSync(full, { withFileTypes: true })
  } catch {
    return { entries: [], more: 0 }
  }
  const visible = entries.filter((e) => !e.name.startsWith('.') && (e.isDirectory() || e.isFile()))
  visible.sort((a, b) => (a.isDirectory() === b.isDirectory() ? a.name.localeCompare(b.name) : a.isDirectory() ? -1 : 1))
  const shown = visible.slice(0, Math.max(0, limit)).map((e) => {
    const p = relPath ? `${relPath}/${e.name}` : e.name
    return e.isDirectory() ? { path: p, name: e.name, type: 'dir' } : { path: p, name: e.name, type: 'file', ...fileKind(e.name) }
  })
  return { entries: shown, more: visible.length - shown.length }
}

// What a card needs about a file or folder, without reading file contents: file count, mtime, the first images
// (covers), the kinds inside. Breadth-first and bounded (WALK_LIMIT entries), so a huge folder costs a bounded walk.
export function summarizeOutbox(relPath) {
  const full = resolveOutboxPath(relPath)
  let st
  try {
    st = lstatSync(full)
  } catch {
    return null
  }
  if (st.isFile()) {
    const k = fileKind(relPath)
    return { isDir: false, count: 1, size: st.size, mtimeMs: st.mtimeMs, covers: k.kind === 'image' ? [relPath] : [], kinds: [k.label] }
  }
  if (!st.isDirectory()) return null
  const covers = []
  const kinds = new Set()
  let count = 0
  let walked = 0
  const queue = [relPath]
  while (queue.length && walked < WALK_LIMIT) {
    const dir = queue.shift()
    let entries
    try {
      entries = readdirSync(path.join(outboxRoot(), dir), { withFileTypes: true })
    } catch {
      continue
    }
    entries.sort((a, b) => a.name.localeCompare(b.name))
    for (const e of entries) {
      if (e.name.startsWith('.') || ++walked > WALK_LIMIT) continue
      const p = `${dir}/${e.name}`
      if (e.isDirectory()) queue.push(p)
      else if (e.isFile()) {
        count++
        const k = fileKind(e.name)
        if (kinds.size < 6) kinds.add(k.label)
        if (k.kind === 'image' && covers.length < 8) covers.push(p)
      }
    }
  }
  return { isDir: true, count, truncated: walked > WALK_LIMIT, mtimeMs: st.mtimeMs, covers, kinds: [...kinds] }
}

// The first `n` bytes of a file as text (a large file is never read whole).
export function readHead(fullPath, n) {
  const fd = openSync(fullPath, 'r')
  try {
    const buf = Buffer.alloc(n)
    const got = readSync(fd, buf, 0, n, 0)
    return buf.subarray(0, got).toString('utf8')
  } finally {
    closeSync(fd)
  }
}

// The first heading and opening text of a markdown or text file (its first 2 KB), for a card. Never throws.
export function outboxPreview(relPath) {
  try {
    const { fullPath } = statFile(relPath)
    const k = fileKind(relPath).kind
    if (k !== 'markdown' && k !== 'text') return null
    const head = readHead(fullPath, 2048)
    const lines = head.split('\n').map((l) => l.trim()).filter(Boolean)
    const h = lines.find((l) => /^#{1,6}\s/.test(l))
    const title = h ? h.replace(/^#{1,6}\s+/, '') : null
    const text = lines.filter((l) => l !== h && !/^#{1,6}\s/.test(l)).join(' ').slice(0, 280)
    return { title, text }
  } catch {
    return null
  }
}

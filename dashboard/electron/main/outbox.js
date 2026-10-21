// The Files tab's reader (G-Eskayo/marvin#89, #402): a read-only view of ~/.claude/outbox. Every file comes back in the
// form the renderer can show best: images as data: URLs read as bytes (the CSP allows img-src data:, same as
// portfolio.js), PDFs as their bytes for the renderer's own pdf.js view (PdfView), text kinds as text, and anything else (or too large, or unreadable) as a card: name, kind, size, reason. Never raw
// bytes decoded as UTF-8. Every path, including images a markdown file embeds, goes through resolveOutboxPath.
import { readFileSync, readdirSync, lstatSync, existsSync, realpathSync } from 'fs'
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

export function listOutboxTree(relPath = '', depth = 0) {
  const currentPath = relPath ? path.join(outboxRoot(), relPath) : outboxRoot()
  if (depth > MAX_DEPTH || !existsSync(currentPath)) return []
  let entries
  try {
    entries = readdirSync(currentPath, { withFileTypes: true })
  } catch {
    return []
  }
  const dirs = []
  const files = []
  for (const entry of entries) {
    const entryPath = relPath ? `${relPath}/${entry.name}` : entry.name
    if (entry.isDirectory()) dirs.push({ path: entryPath, name: entry.name })
    else if (entry.isFile()) files.push({ path: entryPath, name: entry.name })
  }
  dirs.sort((a, b) => a.name.localeCompare(b.name))
  files.sort((a, b) => a.name.localeCompare(b.name))
  return [
    ...dirs.map((d) => ({ path: d.path, type: 'dir', children: listOutboxTree(d.path, depth + 1) })),
    // The kind comes from the name alone: listing never opens a file.
    ...files.map((f) => ({ path: f.path, type: 'file', ...fileKind(f.name) }))
  ]
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

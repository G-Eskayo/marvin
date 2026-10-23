import { createHash } from 'crypto'
import { readFileSync, writeFileSync, mkdirSync, lstatSync, existsSync, readdirSync, statSync, rmSync, renameSync } from 'fs'
import path from 'path'
import { varPath } from './marvin_paths.js'

// Text inside PDF deliverables, for the Docs search (#611). pdf.js (pdfjs-dist, already the dashboard's PDF viewer,
// #570) reads each PDF once, in the background, one at a time; the text is cached on disk by the PDF's content hash, so
// the same bytes at two paths or after a restart are never read again. A search never waits: peek() answers from the
// cache or queues the PDF and answers null, and onReady() tells the search to pick the new text up.
//
// Cost: extraction ~5 ms a page (a 29-page, 50 KB PDF took 140 ms), once per distinct PDF. Disk: at most `maxBytes`
// (20 MB) of text, oldest evicted first, at most `maxTextBytes` (200 KB) per PDF, plus a key map (path|size|mtime ->
// hash). A peek is one stat and one small read. PDFs over `maxPdfBytes` (50 MB, the viewer's own cap) are skipped.

const MAX_PAGES = 500

export async function extractPdfText(bytes) {
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  const doc = await pdfjs.getDocument({ data: new Uint8Array(bytes), isEvalSupported: false, disableFontFace: true, useSystemFonts: false, verbosity: 0 }).promise
  try {
    const parts = []
    for (let i = 1; i <= Math.min(doc.numPages, MAX_PAGES); i++) {
      const page = await doc.getPage(i)
      const content = await page.getTextContent()
      parts.push(content.items.map((x) => x.str || '').join(' '))
      page.cleanup()
    }
    return parts.join('\n')
  } finally {
    await doc.destroy()
  }
}

// Cut to at most `max` UTF-8 bytes without splitting a character.
function capBytes(text, max) {
  const buf = Buffer.from(text, 'utf8')
  if (buf.length <= max) return text
  return buf.subarray(0, max).toString('utf8').replace(/�$/, '')
}

export function createPdfText({
  dir = varPath('pdf-text'),
  extract = extractPdfText,
  onReady = () => {},
  maxBytes = 20 * 1024 * 1024,
  maxTextBytes = 200 * 1024,
  maxPdfBytes = 50 * 1024 * 1024,
  maxKeys = 5000,
  autoDrain = false // the app: a queued PDF starts the background pass on its own
} = {}) {
  const keysFile = () => path.join(dir, 'keys.json')
  const textFile = (hash) => path.join(dir, `${hash}.txt`)
  let keys = null // Map "abs|size|mtimeMs" -> sha256
  const queue = new Set()
  let running = null

  function loadKeys() {
    if (keys) return keys
    try {
      const d = JSON.parse(readFileSync(keysFile(), 'utf8'))
      keys = new Map(Object.entries(d && typeof d === 'object' ? d : {}))
    } catch {
      keys = new Map() // missing or corrupt: rebuilt as PDFs are seen
    }
    return keys
  }
  function saveKeys() {
    try {
      mkdirSync(dir, { recursive: true })
      const entries = [...loadKeys()].filter(([, h]) => existsSync(textFile(h))).slice(-maxKeys)
      keys = new Map(entries)
      writeFileSync(`${keysFile()}.tmp`, JSON.stringify(Object.fromEntries(entries)))
      renameSync(`${keysFile()}.tmp`, keysFile())
    } catch {
      // unwritable: memory still serves this session
    }
  }

  const keyOf = (abs) => {
    try {
      const st = lstatSync(abs)
      if (!st.isFile() || st.size > maxPdfBytes) return null
      return `${abs}|${st.size}|${st.mtimeMs}`
    } catch {
      return null
    }
  }

  function evict(keep) {
    let files
    try {
      files = readdirSync(dir)
        .filter((f) => f.endsWith('.txt'))
        .map((f) => {
          const st = statSync(path.join(dir, f))
          return { f, size: st.size, at: st.mtimeMs }
        })
    } catch {
      return
    }
    let total = files.reduce((n, x) => n + x.size, 0)
    for (const x of files.sort((a, b) => a.at - b.at)) {
      if (total <= maxBytes) break
      if (x.f === `${keep}.txt`) continue
      rmSync(path.join(dir, x.f), { force: true })
      total -= x.size
    }
  }

  // The cached text, or null (not read yet, unreadable, or empty). Queues anything not cached; never throws.
  function peek(abs) {
    const key = keyOf(abs)
    if (!key) return null
    const hash = loadKeys().get(key)
    if (hash) {
      try {
        const text = readFileSync(textFile(hash), 'utf8')
        return text || null
      } catch {
        loadKeys().delete(key) // evicted: read it again
      }
    }
    queue.add(abs)
    if (autoDrain) setImmediate(() => drain())
    return null
  }

  async function pass() {
    let added = false
    while (queue.size) {
      const abs = queue.values().next().value
      queue.delete(abs)
      const key = keyOf(abs)
      if (!key || loadKeys().has(key) && existsSync(textFile(loadKeys().get(key)))) continue
      let bytes
      try {
        bytes = readFileSync(abs)
      } catch {
        continue
      }
      const hash = createHash('sha256').update(bytes).digest('hex')
      if (!existsSync(textFile(hash))) {
        let text = ''
        try {
          text = capBytes(String((await extract(bytes)) || '').replace(/\s+/g, ' ').trim(), maxTextBytes)
        } catch {
          text = '' // unreadable or encrypted: cached as empty, never retried
        }
        try {
          mkdirSync(dir, { recursive: true })
          writeFileSync(textFile(hash), text)
        } catch {
          continue
        }
        evict(hash)
        if (text) added = true
      }
      loadKeys().set(key, hash)
    }
    saveKeys()
    if (added) onReady()
  }

  // Works through the queue, one PDF at a time; concurrent calls share the one pass.
  function drain() {
    if (!running) running = pass().finally(() => (running = null))
    return running
  }

  return { peek, drain, extract }
}

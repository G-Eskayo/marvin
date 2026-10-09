import { createHash } from 'crypto'
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'fs'
import path from 'path'

// Every image in a PR description, for the PR detail view (owner, 2026-10-09: "when I click on the MR, if there are
// UI photos I want them rendered there"). Before this the detail showed only the first image of the pipeline's Dev
// Environment Evidence section, and only as a path; mock-ups and screenshots placed anywhere else were invisible.

const MD_IMAGE = /!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+["']([^"']*)["'])?\s*\)/g
const HTML_IMAGE = /<img\b[^>]*>/gi
const attr = (tag, name) => {
  const m = tag.match(new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'))
  return m ? (m[1] ?? m[2] ?? m[3] ?? '').trim() : ''
}
const MAX_BODY = 200_000
const MAX_IMAGES = 60

// A repo-relative path points at the PR's own branch, where its images were committed.
export function resolvePrImageUrl(src, { repo, headRef } = {}) {
  const url = String(src || '').trim()
  if (!url) return null
  if (/^data:image\//i.test(url)) return url
  if (/^https?:\/\//i.test(url)) return url
  if (/^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith('//')) return null // javascript:, file:, protocol-relative
  if (!repo || !headRef) return null
  const clean = url.replace(/^\.\//, '').replace(/^\/+/, '')
  if (!clean || clean.split('/').includes('..')) return null
  return `https://raw.githubusercontent.com/${repo}/${headRef}/${clean}`
}

// Markdown left on a caption line, reduced to plain words.
function plainText(line) {
  return line
    .replace(MD_IMAGE, '')
    .replace(HTML_IMAGE, '')
    .replace(/<[^>]+>/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_`]/g, '')
    .replace(/^\s*(?:[-*+]|\d+\.)\s+/, '')
    .replace(/^[\s:—–-]+|[\s:—–-]+$/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

const isHeading = (line) => /^\s{0,3}#{1,6}\s+\S/.test(line)
const headingText = (line) => plainText(line.replace(/^\s{0,3}#{1,6}\s+/, '').replace(/\s+#+\s*$/, ''))

// [{ url, alt, group, caption }] in the order they appear. Duplicates are shown once. Pure: no I/O.
export function parsePrImages(body, { repo, headRef } = {}) {
  if (typeof body !== 'string' || !body) return []
  const lines = body.slice(0, MAX_BODY).split('\n')
  const seen = new Set()
  const out = []
  let group = null
  let lastText = null // the last plain line in this section, a caption for an image line that has none of its own
  let inFence = false
  for (const raw of lines) {
    const line = raw.replace(/\r$/, '')
    if (/^\s*(```|~~~)/.test(line)) { inFence = !inFence; continue }
    if (inFence) continue
    if (isHeading(line)) { group = headingText(line) || null; lastText = null; continue }
    const found = []
    for (const m of line.matchAll(MD_IMAGE)) found.push({ index: m.index, src: m[2], alt: m[1].trim(), title: (m[3] || '').trim() })
    for (const m of line.matchAll(HTML_IMAGE)) found.push({ index: m.index, src: attr(m[0], 'src'), alt: attr(m[0], 'alt'), title: attr(m[0], 'title') })
    if (!found.length) {
      const text = plainText(line)
      if (text) lastText = text.length > 240 ? `${text.slice(0, 237)}…` : text
      else if (!line.trim()) { /* a blank line keeps the caption above it */ }
      continue
    }
    const sameLine = plainText(line)
    found.sort((a, b) => a.index - b.index)
    for (const f of found) {
      const url = resolvePrImageUrl(f.src, { repo, headRef })
      if (!url || seen.has(url)) continue
      seen.add(url)
      out.push({ url, alt: f.alt || f.title || '', group, caption: sameLine || lastText || f.title || f.alt || '' })
      if (out.length >= MAX_IMAGES) return out
    }
  }
  return out
}

// Hosts the loader will fetch from, and which of them get the GitHub credential (never sent anywhere else).
const GITHUB_AUTH_HOSTS = new Set(['raw.githubusercontent.com', 'github.com', 'api.github.com'])
const ALLOWED_HOST = (host) =>
  GITHUB_AUTH_HOSTS.has(host) ||
  host.endsWith('.githubusercontent.com') ||
  host === 'github-production-user-asset-6210df.s3.amazonaws.com'

const MIME_BY_EXT = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', svg: 'image/svg+xml' }

function sniffMime(buf, url) {
  if (buf.length >= 8 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) return 'image/png'
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'image/jpeg'
  if (buf.length >= 6 && buf.slice(0, 3).toString('ascii') === 'GIF') return 'image/gif'
  if (buf.length >= 12 && buf.slice(0, 4).toString('ascii') === 'RIFF' && buf.slice(8, 12).toString('ascii') === 'WEBP') return 'image/webp'
  const head = buf.slice(0, 512).toString('utf8').trimStart()
  if (head.startsWith('<svg') || (head.startsWith('<?xml') && head.includes('<svg'))) return 'image/svg+xml'
  const ext = (url.split('?')[0].split('.').pop() || '').toLowerCase()
  return MIME_BY_EXT[ext] || null
}

// Fetches an image's bytes in the main process (so private repos work with the GitHub credential, which never
// reaches the renderer) and returns a data: URL the renderer's CSP already allows. Cached in memory and on disk.
export function createImageLoader({
  fetchFn = globalThis.fetch,
  token = () => process.env.GH_TOKEN || '',
  cacheDir = null,
  maxBytes = 15 * 1024 * 1024,
  timeoutMs = 20_000,
  memEntries = 80
} = {}) {
  const mem = new Map()
  const inflight = new Map()
  const remember = (url, value) => {
    mem.set(url, value)
    if (mem.size > memEntries) mem.delete(mem.keys().next().value)
    return value
  }
  const diskPath = (url) => (cacheDir ? path.join(cacheDir, createHash('sha256').update(url).digest('hex')) : null)

  async function fetchOnce(url) {
    if (/^data:image\//i.test(url)) return { ok: true, dataUrl: url }
    let parsed
    try { parsed = new URL(url) } catch { return { ok: false, reason: 'not a valid image address' } }
    if (parsed.protocol !== 'https:') return { ok: false, reason: 'only https images are loaded' }
    if (!ALLOWED_HOST(parsed.hostname)) return { ok: false, reason: `images from ${parsed.hostname} aren't loaded; open the PR on GitHub` }

    const file = diskPath(url)
    if (file && existsSync(file)) {
      try {
        const cached = JSON.parse(readFileSync(file, 'utf8'))
        if (cached?.dataUrl) return { ok: true, dataUrl: cached.dataUrl }
      } catch { /* a corrupt cache entry is just refetched */ }
    }

    const headers = { Accept: 'image/*,*/*;q=0.5', 'User-Agent': 'marvin-dashboard' }
    const t = token()
    if (t && GITHUB_AUTH_HOSTS.has(parsed.hostname)) headers.Authorization = `token ${t}`
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    let res
    try {
      res = await fetchFn(url, { headers, signal: controller.signal, redirect: 'follow' })
    } catch (error) {
      clearTimeout(timer)
      return { ok: false, reason: error?.name === 'AbortError' ? 'timed out' : `network error (${error?.message || error})` }
    }
    try {
      if (!res.ok) {
        const why = res.status === 404 ? 'not found (404): the file may not be pushed, or the repo is private and the credential lacks access' : `GitHub answered ${res.status}`
        return { ok: false, reason: why }
      }
      const declared = Number(res.headers?.get?.('content-length') || 0)
      if (declared > maxBytes) return { ok: false, reason: `too large (${Math.round(declared / 1048576)} MB)` }
      const buf = Buffer.from(await res.arrayBuffer())
      if (buf.length > maxBytes) return { ok: false, reason: `too large (${Math.round(buf.length / 1048576)} MB)` }
      const mime = sniffMime(buf, url)
      if (!mime) return { ok: false, reason: 'not an image' }
      const dataUrl = `data:${mime};base64,${buf.toString('base64')}`
      if (file) {
        try { mkdirSync(cacheDir, { recursive: true }); writeFileSync(file, JSON.stringify({ url, dataUrl })) } catch { /* cache is best effort */ }
      }
      return { ok: true, dataUrl }
    } finally {
      clearTimeout(timer)
    }
  }

  return {
    async load(url) {
      if (mem.has(url)) return mem.get(url)
      if (inflight.has(url)) return inflight.get(url)
      const p = fetchOnce(String(url || '')).then((result) => {
        inflight.delete(url)
        return result.ok ? remember(url, result) : result // failures aren't cached, so a retry can succeed
      })
      inflight.set(url, p)
      return p
    }
  }
}

import { createHash } from 'crypto'
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'fs'
import path from 'path'

// Every image and recording in a PR description, for the PR detail view. Owner, 2026-10-09: "when I click on the MR,
// if there are UI photos I want them rendered there", and for anything visual he wants to SEE it working: GIFs that
// animate and screen recordings that play, not only stills. Before this the detail showed only the first image of
// the pipeline's Dev Environment Evidence section, and only as a path.

const MD_IMAGE = /!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+["']([^"']*)["'])?\s*\)/g
const MD_LINK = /(?<!!)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+["']([^"']*)["'])?\s*\)/g
const HTML_IMAGE = /<img\b[^>]*>/gi
const HTML_VIDEO = /<video\b[^>]*>/gi
const HTML_SOURCE = /<source\b[^>]*>/gi
const BARE_URL = /(?<![("'=<])\bhttps:\/\/[^\s<>()"']+/g
const VIDEO_EXT = /\.(mp4|mov|m4v|webm)(?:[?#][^\s]*)?$/i
const USER_ATTACHMENT = /^https:\/\/github\.com\/user-attachments\/assets\/[0-9a-f-]+\/?$/i
const attr = (tag, name) => {
  const m = tag.match(new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'))
  return m ? (m[1] ?? m[2] ?? m[3] ?? '').trim() : ''
}
const MAX_BODY = 200_000
const MAX_ITEMS = 60

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
    .replace(BARE_URL, '')
    .replace(/[*_`]/g, '')
    .replace(/^\s*(?:[-*+]|\d+\.)\s+/, '')
    .replace(/^[\s:—–-]+|[\s:—–-]+$/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

const isHeading = (line) => /^\s{0,3}#{1,6}\s+\S/.test(line)
const headingText = (line) => plainText(line.replace(/^\s{0,3}#{1,6}\s+/, '').replace(/\s+#+\s*$/, ''))

// Everything on one line that should be shown, with where it starts (for left-to-right order).
function mediaOnLine(line) {
  const found = []
  for (const m of line.matchAll(MD_IMAGE)) {
    found.push({ index: m.index, src: m[2], alt: m[1].trim(), title: (m[3] || '').trim(), kind: VIDEO_EXT.test(m[2]) ? 'video' : 'image' })
  }
  for (const m of line.matchAll(HTML_IMAGE)) {
    found.push({ index: m.index, src: attr(m[0], 'src'), alt: attr(m[0], 'alt'), title: attr(m[0], 'title'), kind: 'image' })
  }
  for (const m of line.matchAll(HTML_VIDEO)) {
    const src = attr(m[0], 'src')
    if (src) found.push({ index: m.index, src, alt: attr(m[0], 'title') || attr(m[0], 'aria-label'), title: '', kind: 'video' })
  }
  if (/<video\b/i.test(line)) {
    for (const m of line.matchAll(HTML_SOURCE)) found.push({ index: m.index, src: attr(m[0], 'src'), alt: '', title: '', kind: 'video' })
  }
  // A link to a recording: [demo](https://…/demo.mp4)
  for (const m of line.matchAll(MD_LINK)) {
    if (VIDEO_EXT.test(m[2])) found.push({ index: m.index, src: m[2], alt: m[1].trim(), title: (m[3] || '').trim(), kind: 'video' })
  }
  // A bare recording URL, or a bare GitHub attachment (GitHub shows those inline; images use ![](…)).
  const bareLine = line.trim()
  for (const m of line.matchAll(BARE_URL)) {
    const url = m[0].replace(/[.,;:!?]+$/, '')
    if (VIDEO_EXT.test(url)) found.push({ index: m.index, src: url, alt: '', title: '', kind: 'video' })
    else if (USER_ATTACHMENT.test(url) && bareLine === url) found.push({ index: m.index, src: url, alt: '', title: '', kind: 'auto' })
  }
  return found.sort((a, b) => a.index - b.index)
}

// [{ url, kind: 'image'|'video'|'auto', alt, group, caption }] in the order they appear; duplicates once. Pure: no I/O.
export function parsePrImages(body, { repo, headRef } = {}) {
  if (typeof body !== 'string' || !body) return []
  const lines = body.slice(0, MAX_BODY).split('\n')
  const seen = new Set()
  const out = []
  let group = null
  let lastText = null // the last plain line in this section, a caption for a media line that has none of its own
  let inFence = false
  let inVideo = false // <video> … <source> … </video> across lines
  for (const raw of lines) {
    const line = raw.replace(/\r$/, '')
    if (/^\s*(```|~~~)/.test(line)) { inFence = !inFence; continue }
    if (inFence) continue
    if (isHeading(line)) { group = headingText(line) || null; lastText = null; continue }
    const found = mediaOnLine(line)
    if (inVideo || (/<video\b/i.test(line) && !/<\/video>/i.test(line))) {
      for (const m of line.matchAll(HTML_SOURCE)) if (!found.some((f) => f.index === m.index)) found.push({ index: m.index, src: attr(m[0], 'src'), alt: '', title: '', kind: 'video' })
      inVideo = !/<\/video>/i.test(line)
    }
    if (!found.length) {
      const text = plainText(line)
      if (text) lastText = text.length > 240 ? `${text.slice(0, 237)}…` : text
      continue
    }
    const sameLine = plainText(line)
    for (const f of found) {
      const url = resolvePrImageUrl(f.src, { repo, headRef })
      if (!url || seen.has(url)) continue
      seen.add(url)
      out.push({ url, kind: f.kind, alt: f.alt || f.title || '', group, caption: sameLine || lastText || f.title || f.alt || '' })
      if (out.length >= MAX_ITEMS) return out
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

const MIME_BY_EXT = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', svg: 'image/svg+xml',
  mp4: 'video/mp4', m4v: 'video/mp4', mov: 'video/quicktime', webm: 'video/webm'
}
const EXT_BY_MIME = { 'video/mp4': 'mp4', 'video/quicktime': 'mov', 'video/webm': 'webm' }

export function sniffMime(buf, url = '') {
  if (buf.length >= 8 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) return 'image/png'
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'image/jpeg'
  if (buf.length >= 6 && buf.slice(0, 3).toString('ascii') === 'GIF') return 'image/gif'
  if (buf.length >= 12 && buf.slice(0, 4).toString('ascii') === 'RIFF' && buf.slice(8, 12).toString('ascii') === 'WEBP') return 'image/webp'
  if (buf.length >= 4 && buf[0] === 0x1a && buf[1] === 0x45 && buf[2] === 0xdf && buf[3] === 0xa3) return 'video/webm'
  if (buf.length >= 12 && buf.slice(4, 8).toString('ascii') === 'ftyp') {
    return buf.slice(8, 10).toString('ascii') === 'qt' ? 'video/quicktime' : 'video/mp4'
  }
  if (buf.length >= 8 && ['moov', 'mdat', 'wide', 'free'].includes(buf.slice(4, 8).toString('ascii'))) return 'video/quicktime'
  const head = buf.slice(0, 512).toString('utf8').trimStart()
  if (head.startsWith('<svg') || (head.startsWith('<?xml') && head.includes('<svg'))) return 'image/svg+xml'
  const ext = (String(url).split(/[?#]/)[0].split('.').pop() || '').toLowerCase()
  return MIME_BY_EXT[ext] || null
}

const hashOf = (url) => createHash('sha256').update(url).digest('hex')

// The cached recording behind a prmedia:// id, or null. Only a 64-hex id inside the cache directory is ever served.
export function mediaFileFor(cacheDir, id) {
  if (!cacheDir || !/^[0-9a-f]{64}$/.test(String(id || ''))) return null
  for (const ext of Object.values(EXT_BY_MIME)) {
    const file = path.join(cacheDir, `${id}.${ext}`)
    if (existsSync(file)) return { file, mime: Object.keys(EXT_BY_MIME).find((m) => EXT_BY_MIME[m] === ext) }
  }
  return null
}

// Fetches media bytes in the main process (so private repos work with the GitHub credential, which never reaches the
// renderer). Images come back as data: URLs the renderer's CSP allows; recordings (too big for that) are written to
// the cache directory and come back as prmedia://media/<id>, which the main process streams with seeking.
export function createImageLoader({
  fetchFn = globalThis.fetch,
  token = () => process.env.GH_TOKEN || '',
  cacheDir = null,
  maxBytes = 15 * 1024 * 1024,
  maxVideoBytes = 100 * 1024 * 1024,
  timeoutMs = 20_000,
  videoTimeoutMs = 120_000,
  memEntries = 80,
  mediaUrl = (id) => `prmedia://media/${id}`
} = {}) {
  const mem = new Map()
  const inflight = new Map()
  const remember = (url, value) => {
    mem.set(url, value)
    if (mem.size > memEntries) mem.delete(mem.keys().next().value)
    return value
  }
  const mb = (n) => `${Math.round(n / 1048576)} MB`

  function fromDisk(url) {
    if (!cacheDir) return null
    const id = hashOf(url)
    const video = mediaFileFor(cacheDir, id)
    if (video) return { ok: true, kind: 'video', mime: video.mime, src: mediaUrl(id) }
    const file = path.join(cacheDir, id)
    if (!existsSync(file)) return null
    try {
      const cached = JSON.parse(readFileSync(file, 'utf8'))
      if (cached?.dataUrl) return { ok: true, kind: 'image', mime: cached.mime || null, src: cached.dataUrl, dataUrl: cached.dataUrl }
    } catch { /* a corrupt cache entry is just refetched */ }
    return null
  }

  async function fetchOnce(url, kindHint) {
    if (/^data:image\//i.test(url)) return { ok: true, kind: 'image', src: url, dataUrl: url }
    let parsed
    try { parsed = new URL(url) } catch { return { ok: false, reason: 'not a valid address' } }
    if (parsed.protocol !== 'https:') return { ok: false, reason: 'only https media is loaded' }
    if (!ALLOWED_HOST(parsed.hostname)) return { ok: false, reason: `media from ${parsed.hostname} isn't loaded; open the PR on GitHub` }

    const cached = fromDisk(url)
    if (cached) return cached

    const expectVideo = kindHint === 'video' || VIDEO_EXT.test(parsed.pathname)
    const expectImage = kindHint === 'image' || /\.(png|jpe?g|gif|webp|svg)$/i.test(parsed.pathname)
    const cap = expectImage && !expectVideo ? maxBytes : maxVideoBytes
    const headers = { Accept: expectVideo ? 'video/*,*/*;q=0.5' : 'image/*,video/*;q=0.8,*/*;q=0.5', 'User-Agent': 'marvin-dashboard' }
    const t = token()
    if (t && GITHUB_AUTH_HOSTS.has(parsed.hostname)) headers.Authorization = `token ${t}`
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), expectVideo || kindHint === 'auto' ? videoTimeoutMs : timeoutMs)
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
      if (declared > cap) return { ok: false, reason: `too large (${mb(declared)})` }
      let buf
      try {
        buf = Buffer.from(await res.arrayBuffer())
      } catch (error) {
        return { ok: false, reason: error?.name === 'AbortError' ? 'timed out' : `download failed (${error?.message || error})` }
      }
      if (buf.length > cap) return { ok: false, reason: `too large (${mb(buf.length)})` }
      const mime = sniffMime(buf, parsed.pathname)
      if (!mime) return { ok: false, reason: 'not an image or recording' }
      const id = hashOf(url)
      if (mime.startsWith('video/')) {
        if (!cacheDir) return { ok: false, reason: 'recordings need the media cache, which is not set up' }
        try {
          mkdirSync(cacheDir, { recursive: true })
          writeFileSync(path.join(cacheDir, `${id}.${EXT_BY_MIME[mime]}`), buf)
        } catch (error) {
          return { ok: false, reason: `couldn't save the recording (${error?.message || error})` }
        }
        return { ok: true, kind: 'video', mime, src: mediaUrl(id) }
      }
      if (buf.length > maxBytes) return { ok: false, reason: `too large (${mb(buf.length)})` }
      const dataUrl = `data:${mime};base64,${buf.toString('base64')}`
      if (cacheDir) {
        try { mkdirSync(cacheDir, { recursive: true }); writeFileSync(path.join(cacheDir, id), JSON.stringify({ url, mime, dataUrl })) } catch { /* cache is best effort */ }
      }
      return { ok: true, kind: 'image', mime, src: dataUrl, dataUrl }
    } finally {
      clearTimeout(timer)
    }
  }

  return {
    async load(url, kindHint = null) {
      if (mem.has(url)) return mem.get(url)
      if (inflight.has(url)) return inflight.get(url)
      const p = fetchOnce(String(url || ''), kindHint).then((result) => {
        inflight.delete(url)
        return result.ok ? remember(url, result) : result // failures aren't cached, so a retry can succeed
      })
      inflight.set(url, p)
      return p
    }
  }
}

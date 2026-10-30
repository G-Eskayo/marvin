import path from 'path'

// Clickable mock-ups on a PR branch, opened inside MARVIN (G-Eskayo/marvin#938). The owner reviews only in the
// dashboard, so a mock-up page (docs/design/<name>/index.html with its scripts beside it) has to open there, read from
// the PR's head commit, in a sandboxed window that can't reach the network, the app, or window.api.
// This file is the pure part: which PRs carry a mock-up, which files a page may load, which requests go through, and
// where the bytes come from (the local clone, else GitHub signed in). mockup_window.js is the Electron glue.

export const MOCKUP_SCHEME = 'marvin-mockup'
const MARKER = /<!--\s*marvin:mockup\s+([^\s>]+)\s*-->/gi
const DESIGN_PAGE = /^docs\/design\/(?:.+\/)?index\.html$/
const MAX_MOCKUPS = 8

// Code (fenced or inline) is quoted text: a ticket that explains the marker in backticks doesn't carry a mock-up.
function withoutCode(body) {
  return String(body || '')
    .replace(/^\s*(```|~~~)[\s\S]*?^\s*\1[^\n]*$/gm, '')
    .replace(/`[^`\n]*`/g, '')
}

// A repo-relative page path that is safe to name: an .html file, no traversal, no scheme, no leading slash.
export function cleanPagePath(p) {
  const s = String(p || '').trim().replace(/^\.\//, '')
  if (!s || s.startsWith('/') || s.includes('\\') || s.includes('\0') || /^[a-z][a-z0-9+.-]*:/i.test(s)) return null
  if (!/\.html?$/i.test(s)) return null
  const parts = s.split('/')
  if (parts.some((x) => x === '..' || x === '.' || x === '' || x.includes('%'))) return null
  return s
}

const mockupOf = (page) => {
  const dir = path.posix.dirname(page)
  return { path: page, dir: dir === '.' ? '' : dir, name: dir === '.' ? page : path.posix.basename(dir) }
}

// The PR's mock-ups: [{ path, dir, name }]. A `<!-- marvin:mockup path -->` marker in the body wins over the changed
// files (it names exactly which page to open); without one, every changed docs/design/**/index.html is one.
export function detectMockups(body, files) {
  const marked = []
  for (const m of withoutCode(body).matchAll(MARKER)) {
    const page = cleanPagePath(m[1])
    if (page && !marked.includes(page)) marked.push(page)
  }
  const pages = marked.length
    ? marked
    : [...new Set((Array.isArray(files) ? files : []).map((f) => (typeof f === 'string' ? f : f?.path)).filter((p) => typeof p === 'string' && DESIGN_PAGE.test(p) && cleanPagePath(p)))]
  return pages.slice(0, MAX_MOCKUPS).map(mockupOf)
}

// The repo path a request inside a mock-up window may read, or null. The page's own folder only: no `..` (plain or
// percent-encoded, once or twice), no absolute paths, no backslashes, nothing outside `dir`. An empty path is the page.
export function resolveMockupPath(dir, requestPath, page = 'index.html') {
  let raw = String(requestPath ?? '')
  let decoded
  try {
    decoded = decodeURIComponent(raw)
  } catch {
    return null
  }
  // A second layer of encoding (%252e) is never a real file name in a mock-up; refuse it instead of guessing.
  if (/%[0-9a-f]{2}/i.test(decoded)) return null
  if (decoded.includes('\0') || decoded.includes('\\')) return null
  const rel = decoded.replace(/^\/+/, '') || page
  if (rel.split('/').some((x) => x === '..')) return null
  const base = String(dir || '').replace(/\/+$/, '')
  const joined = path.posix.normalize(base ? `${base}/${rel}` : rel)
  if (joined.startsWith('/') || joined.startsWith('..')) return null
  if (base && !joined.startsWith(`${base}/`)) return null
  return joined
}

// Requests a mock-up window may make: its own protocol, and nothing else (no http(s), ws, file, other app schemes).
export function mockupRequestAllowed(url) {
  try {
    return new URL(String(url)).protocol === `${MOCKUP_SCHEME}:`
  } catch {
    return false
  }
}

const MIME = {
  html: 'text/html; charset=utf-8', htm: 'text/html; charset=utf-8', js: 'text/javascript; charset=utf-8', mjs: 'text/javascript; charset=utf-8',
  css: 'text/css; charset=utf-8', json: 'application/json; charset=utf-8', svg: 'image/svg+xml', png: 'image/png', jpg: 'image/jpeg',
  jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', woff: 'font/woff', woff2: 'font/woff2', ttf: 'font/ttf', otf: 'font/otf',
  txt: 'text/plain; charset=utf-8', md: 'text/plain; charset=utf-8', mp4: 'video/mp4', webm: 'video/webm'
}
export const mimeFor = (p) => MIME[(String(p).split('.').pop() || '').toLowerCase()] || 'application/octet-stream'

// Every response carries this as well, so the page itself refuses to reach out even before the session filter does.
export const MOCKUP_CSP = `default-src ${MOCKUP_SCHEME}: data: blob: 'unsafe-inline'; script-src ${MOCKUP_SCHEME}: 'unsafe-inline'; connect-src ${MOCKUP_SCHEME}:; frame-ancestors 'none'; form-action 'none'`

// The plain words the detail shows when a mock-up can't be opened.
export const GONE = {
  branch: 'This mock-up is gone: its branch was deleted',
  file: "This mock-up is gone: its page isn't on the branch any more",
  access: "This mock-up couldn't be read from GitHub: the sign-in doesn't reach this repo",
  network: "This mock-up couldn't be read: GitHub didn't answer"
}

const REPO_RE = /^[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+$/
const SHA_RE = /^[0-9a-f]{7,40}$/i
const REF_RE = /^[A-Za-z0-9._\/-]+$/

// Reads one file of a PR at its head commit. Local first (a clone on this Mac that has, or can fetch, the commit),
// else GitHub's contents API with the shared token. Returns { ok, body: Buffer, mime } or { ok: false, gone, reason }.
// gone: 'branch' (the commit/ref is no longer there), 'file' (the commit is, the file isn't), 'access', 'network'.
export function createMockupSource({
  exec, // (cmd, args, opts) => Promise<{ stdout: Buffer|string }>
  resolveClone = async () => null, // (repoName) => dir | null
  fetchFn = globalThis.fetch,
  token = () => process.env.GH_TOKEN || '',
  timeoutMs = 20_000,
  maxBytes = 20 * 1024 * 1024
} = {}) {
  const cloneOf = new Map() // repo -> Promise<dir|null>, so a page with ten files looks once
  const hasCommit = new Map() // `${dir}@${sha}` -> Promise<boolean>

  const git = (dir, args) => exec('git', ['-C', dir, ...args], { encoding: 'buffer', maxBuffer: maxBytes, timeout: 60_000 })

  async function localHas(dir, sha, number) {
    const key = `${dir}@${sha}`
    if (!hasCommit.has(key)) {
      hasCommit.set(key, (async () => {
        const present = () => git(dir, ['cat-file', '-e', `${sha}^{commit}`]).then(() => true, () => false)
        if (await present()) return true
        // The PR's head ref stays on GitHub after its branch is deleted; fetching it brings the commit even then.
        const refs = number ? [`refs/pull/${Number(number)}/head`, sha] : [sha]
        for (const ref of refs) {
          try { await git(dir, ['fetch', '--quiet', '--no-tags', 'origin', ref]) } catch { continue }
          if (await present()) return true
        }
        return false
      })())
    }
    return hasCommit.get(key)
  }

  async function readLocal(repo, sha, file, number) {
    if (!exec || !SHA_RE.test(sha)) return null
    const name = repo.split('/')[1]
    if (!cloneOf.has(repo)) cloneOf.set(repo, Promise.resolve(resolveClone(name)).catch(() => null))
    const dir = await cloneOf.get(repo)
    if (!dir || !(await localHas(dir, sha, number))) return null
    try {
      const { stdout } = await git(dir, ['show', `${sha}:${file}`])
      return { ok: true, body: Buffer.isBuffer(stdout) ? stdout : Buffer.from(String(stdout)), mime: mimeFor(file), source: 'local' }
    } catch {
      return { ok: false, gone: 'file', reason: GONE.file }
    }
  }

  async function readRemote(repo, ref, file) {
    const url = `https://api.github.com/repos/${repo}/contents/${file.split('/').map(encodeURIComponent).join('/')}?ref=${encodeURIComponent(ref)}`
    const headers = { Accept: 'application/vnd.github.raw', 'User-Agent': 'marvin-dashboard', 'X-GitHub-Api-Version': '2022-11-28' }
    const t = token()
    if (t) headers.Authorization = `Bearer ${t}`
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      let res
      try {
        res = await fetchFn(url, { headers, signal: controller.signal })
      } catch {
        return { ok: false, gone: 'network', reason: GONE.network }
      }
      if (res.status === 404 || res.status === 422) {
        let message = ''
        try { message = String((await res.json())?.message || '') } catch { /* not json */ }
        if (/no commit found|not a valid ref|branch .*not found/i.test(message)) return { ok: false, gone: 'branch', reason: GONE.branch }
        // A private repo answers 404 to a token without access; with no token at all that's the likelier reason.
        if (!t) return { ok: false, gone: 'access', reason: GONE.access }
        return { ok: false, gone: 'file', reason: GONE.file }
      }
      if (res.status === 401 || res.status === 403) return { ok: false, gone: 'access', reason: GONE.access }
      if (!res.ok) return { ok: false, gone: 'network', reason: `${GONE.network} (${res.status})` }
      const buf = Buffer.from(await res.arrayBuffer())
      if (buf.length > maxBytes) return { ok: false, gone: 'file', reason: 'This mock-up file is too large to open' }
      return { ok: true, body: buf, mime: mimeFor(file), source: 'github' }
    } finally {
      clearTimeout(timer)
    }
  }

  return {
    // target: { repo, sha, ref, number }; file: a repo path already checked by resolveMockupPath.
    async read(target, file) {
      const { repo, sha, ref, number } = target || {}
      if (!REPO_RE.test(String(repo || '')) || !file) return { ok: false, gone: 'file', reason: GONE.file }
      const at = SHA_RE.test(String(sha || '')) ? sha : REF_RE.test(String(ref || '')) ? ref : null
      if (!at) return { ok: false, gone: 'branch', reason: GONE.branch }
      const local = await readLocal(repo, at, file, number)
      if (local) return local
      return readRemote(repo, at, file)
    }
  }
}

import { realpathSync, lstatSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { cleanPagePath } from './mockups.js'
import { fileKind } from '../../src/lib/file_kinds.js'

// `marvin show` (G-Eskayo/marvin#715): a session asks the running dashboard to show Gil one thing, in that project's
// own viewer window. This file is the pure part: what a request may name, where a path may live, and which project a
// shown item belongs to. show_window.js is the Electron glue; lib/marvin_show.py is the CLI that sends the request.

// Temp folders: a session's scratchpad lives here and Gil can't find it later. The CLI copies these into the outbox
// first; the dashboard never shows a temp path itself (nothing Gil is shown lives only in temp).
const TEMP_ROOTS = ['/tmp', '/private/tmp', '/var/folders', '/private/var/folders']

// File names that are secrets wherever they sit, even inside an allowed root.
const SECRET_NAME = /^(\.env(\..*)?|\.gh-token|\.netrc|\.npmrc|\.pypirc|id_[a-z0-9]+(\.pub)?|.*\.(pem|key|p12|pfx|keychain(-db)?))$/i
const SECRET_DIR = new Set(['.ssh', '.gnupg', '.aws'])

const within = (p, root) => p === root || p.startsWith(root.endsWith(path.sep) ? root : root + path.sep)

export function isTempPath(p) {
  const s = path.resolve(String(p || ''))
  return TEMP_ROOTS.some((r) => within(s, r))
}

// Where a shown file may live: the outbox, MARVIN itself, every project's local clone, and ~/Developer.
export function allowedRoots({ home = homedir(), projects = [] } = {}) {
  const roots = new Set([path.join(home, '.claude', 'outbox'), path.join(home, '.agents'), path.join(home, 'Developer')])
  for (const p of projects) for (const lp of p?.localPaths || []) if (typeof lp === 'string' && path.isAbsolute(lp)) roots.add(path.resolve(lp))
  return [...roots]
}

// A local path the dashboard may show, judged on where it really is (a symlink pointing out is refused).
// Returns { ok: true, real, size } or { ok: false, reason } in plain words.
export function checkShowPath(p, { roots, realpath = realpathSync.native ?? realpathSync, stat = lstatSync } = {}) {
  if (typeof p !== 'string' || !p.trim()) return { ok: false, reason: 'No file named' }
  if (!path.isAbsolute(p)) return { ok: false, reason: 'The path must be absolute' }
  if (p.includes('\0')) return { ok: false, reason: 'Bad path' }
  let real
  try {
    real = realpath(p)
  } catch {
    return { ok: false, reason: `Not found: ${p}` }
  }
  if (isTempPath(real)) return { ok: false, reason: 'That file is in a temp folder; marvin show copies it into the outbox first' }
  const realRoots = (roots || []).map((r) => {
    try {
      return realpath(r)
    } catch {
      return path.resolve(r)
    }
  })
  if (!realRoots.some((r) => within(real, r))) return { ok: false, reason: 'Outside the folders MARVIN shows from (the outbox, ~/.agents, project clones, ~/Developer)' }
  if (real.split(path.sep).some((part) => SECRET_DIR.has(part)) || SECRET_NAME.test(path.basename(real))) return { ok: false, reason: 'That looks like a secret, so it is never shown' }
  let st
  try {
    st = stat(real)
  } catch {
    return { ok: false, reason: `Not found: ${p}` }
  }
  if (!st.isFile()) return { ok: false, reason: 'Only a file can be shown, not a folder' }
  return { ok: true, real, size: st.size }
}

const REPO_RE = /^[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+$/
const REF_RE = /^[A-Za-z0-9._\/-]+$/
const SLUG_RE = /^[A-Za-z0-9:_.-]{1,100}$/

// A repo-relative path for a PR file: like cleanPagePath, but any kind of file (an image, a plan), not only .html.
export function cleanRepoPath(p) {
  const s = String(p || '').trim().replace(/^\.\//, '')
  if (!s || s.startsWith('/') || s.includes('\\') || s.includes('\0') || /^[a-z][a-z0-9+.-]*:/i.test(s)) return null
  if (s.split('/').some((x) => x === '..' || x === '.' || x === '' || x.includes('%'))) return null
  return s
}

// The request body the CLI posts to /show, checked and normalised. One of:
//   { kind: 'file', path }                       a local file (absolute)
//   { kind: 'pr', repo, number?, ref?, path }    a file on a PR branch or a ref (repo-relative)
//   { kind: 'url', url }                         a web address (shown as a link Gil opens in his browser)
// plus optional { project, label }. Returns { ok: true, req } or { ok: false, reason }.
export function parseShowRequest(body) {
  const b = body && typeof body === 'object' ? body : {}
  const extra = {}
  if (b.project != null) {
    if (typeof b.project !== 'string' || !SLUG_RE.test(b.project)) return { ok: false, reason: 'Bad project id' }
    extra.project = b.project
  }
  if (b.label != null) extra.label = String(b.label).slice(0, 200)
  if (b.outboxName != null) extra.outboxName = String(b.outboxName).slice(0, 300)
  if (b.kind === 'file') {
    if (typeof b.path !== 'string' || !path.isAbsolute(b.path)) return { ok: false, reason: 'A file must be named by its absolute path' }
    return { ok: true, req: { kind: 'file', path: b.path, ...extra } }
  }
  if (b.kind === 'pr') {
    const repo = String(b.repo || '')
    if (!REPO_RE.test(repo)) return { ok: false, reason: 'Bad repo (owner/name)' }
    const file = cleanRepoPath(b.path)
    if (!file) return { ok: false, reason: 'Bad file path on the branch' }
    const number = b.number == null ? null : Number(b.number)
    if (number != null && !(Number.isInteger(number) && number > 0)) return { ok: false, reason: 'Bad PR number' }
    const ref = b.ref == null ? null : String(b.ref)
    if (ref != null && !REF_RE.test(ref)) return { ok: false, reason: 'Bad branch name' }
    if (number == null && ref == null) return { ok: false, reason: 'Name the PR (--pr) or a branch' }
    return { ok: true, req: { kind: 'pr', repo, number, ref, path: file, ...extra } }
  }
  if (b.kind === 'url') {
    let u
    try {
      u = new URL(String(b.url))
    } catch {
      return { ok: false, reason: 'Bad web address' }
    }
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return { ok: false, reason: 'Only http(s) addresses are shown' }
    return { ok: true, req: { kind: 'url', url: u.toString(), ...extra } }
  }
  return { ok: false, reason: 'Say what to show: a file, a PR file or a web address' }
}

// The project a shown item belongs to, and how that was decided:
//   1. an outbox item: the Docs tab's own match for it (deliverables.js), so the window and the Docs tab agree;
//   2. a file in a project's local clone (longest clone path wins: ~/.agents/instance before ~/.agents);
//   3. a PR file: the project whose repo it is;
//   4. the project the CLI named (the session's own repo), when it is in the catalog.
// Else the shared "Unsorted" window. Returns { id, name, how }.
export const UNSORTED = { id: '__unsorted__', name: 'Unsorted' }
export function projectFor(req, { real = null, outboxRoot, view = null, projects = [], matchOutboxName = null } = {}) {
  const byId = new Map(projects.map((p) => [p.id, p]))
  const named = (id, how) => ({ id, name: byId.get(id)?.name || id, how })
  if (real && outboxRoot && within(real, outboxRoot)) {
    const rel = path.relative(outboxRoot, real).split(path.sep).join('/')
    let best = null
    for (const [id, entries] of Object.entries(view?.byProject || {})) {
      for (const e of entries || []) {
        if ((rel === e.path || rel.startsWith(`${e.path}/`)) && (!best || e.path.length > best.len)) best = { id, len: e.path.length }
      }
    }
    if (best) return named(best.id, 'outbox')
    // Not in the saved match map yet (copied a moment ago): match its top-level name the way deliverables.js does.
    const top = rel.split('/')[0]
    const m = matchOutboxName?.(top)
    if (m?.id) return named(m.id, 'outbox')
  }
  if (req?.outboxName && matchOutboxName) {
    const m = matchOutboxName(req.outboxName)
    if (m?.id) return named(m.id, 'outbox')
  }
  if (real) {
    let best = null
    for (const p of projects) {
      for (const lp of p?.localPaths || []) {
        if (typeof lp === 'string' && within(real, path.resolve(lp)) && (!best || lp.length > best.len)) best = { id: p.id, len: lp.length }
      }
    }
    if (best) return named(best.id, 'clone')
  }
  if (req?.kind === 'pr') {
    const p = projects.find((x) => String(x.repo || '').toLowerCase() === req.repo.toLowerCase())
    if (p) return named(p.id, 'repo')
  }
  if (req?.project && byId.has(req.project)) return named(req.project, 'named')
  return { ...UNSORTED, how: 'none' }
}

// What the viewer draws for an item, by kind: HTML runs in the sandboxed frame; everything else goes through the Docs
// viewer (FileView), as it does in the Docs tab.
export function viewKind(name) {
  const k = fileKind(name).kind
  return k === 'html' && cleanPagePath(path.posix.basename(String(name))) ? 'html' : k
}

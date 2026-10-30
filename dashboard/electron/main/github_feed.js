import { readFileSync, statSync } from 'fs'
import { homedir } from 'os'
import { join } from 'path'

// marvin#954: mac-mini-2012 holds no secrets (ADR 0069), so its dashboard never calls GitHub. The M4 Mini's webhook
// server writes what GitHub says (each registered repo's open PRs and board data) to github-feed.json
// (webhook-server/github_feed_writer.js); the box copies it over the observer key every 2 minutes, beside the Mini's
// health-status.json (config/mac-mini-2012/marvin-observer-feed.sh), and this module answers from that copy.
//
// Feed shape (times are ms since the epoch, on the Mini's clock):
//   { version: 1, host, alive_at, repos: { "owner/name": { prs: { at, value: [...] }, board: { at, value: {...} } } } }
// alive_at is the Mini's change watch saying "I looked at GitHub and nothing changed", so a quiet repo with an old
// `at` is still current; when alive_at stops moving, the Mini isn't answering.

export const FEED_NAME = 'github-feed.json'
export const FEED_PATH = join(homedir(), '.claude', 'logs', FEED_NAME)
// Older than this (either the box's copy or the Mini's last look at GitHub) = the Mini isn't answering. The copy runs
// every 2 min and the Mini's watch every 20 s, so 10 min is several missed rounds, not one slow one.
export const STALE_MS = 10 * 60_000

// Errors from here say where the data comes from and never use words that read as "sign in again" (pr_fetch_status.js
// maps /auth|credentials|401/ to "GitHub sign-in expired", which is the message this replaces).
export class FeedError extends Error {
  constructor(message) {
    super(message)
    this.name = 'FeedError'
    this.fromFeed = true
  }
}

// Same rule as lib/machine_profile.py pull_only(): a registered device is pull-only when it doesn't accept untagged
// ("general") work; an unregistered machine is pull-only unless it is a Mac. MARVIN_PULL_ONLY=1/0 overrides (tests,
// screenshots). O(1).
export function isPullOnlyNode({ deviceId = null, registry = {}, platform = process.platform, env = process.env } = {}) {
  if (env.MARVIN_PULL_ONLY === '1') return true
  if (env.MARVIN_PULL_ONLY === '0') return false
  const me = deviceId ? registry?.[deviceId] : null
  if (!me) return platform !== 'darwin'
  const accepts = me.accepts ?? ['general']
  return !Array.isArray(accepts) || !accepts.includes('general')
}

// The device registry (~/.claude/marvin-network.json) as { id: entry }; {} when missing or unreadable.
export function readNetworkRegistry(path = join(homedir(), '.claude', 'marvin-network.json'), read = (p) => readFileSync(p, 'utf-8')) {
  try {
    const devices = JSON.parse(read(path))?.devices
    return devices && typeof devices === 'object' ? devices : {}
  } catch {
    return {}
  }
}

const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v)

// The feed, or why there is none. `copiedAt` is the copy's mtime on this machine's clock. Never throws.
export function readFeed(path = FEED_PATH, { read = (p) => readFileSync(p, 'utf-8'), mtime = (p) => statSync(p).mtimeMs } = {}) {
  let text
  try {
    text = read(path)
  } catch {
    return { feed: null, copiedAt: null, problem: 'missing' }
  }
  let feed
  try {
    feed = JSON.parse(text)
  } catch {
    return { feed: null, copiedAt: null, problem: 'unreadable' }
  }
  if (!isObj(feed) || !isObj(feed.repos)) return { feed: null, copiedAt: null, problem: 'unreadable' }
  let copiedAt = null
  try {
    copiedAt = mtime(path)
  } catch {
    copiedAt = null
  }
  return { feed, copiedAt, problem: null }
}

// How old the box's view of GitHub is: the older of "when the box last copied the feed" and "when the Mini last
// looked at GitHub". A clock that runs ahead (skew between the machines) never makes an age negative.
export function feedAge({ feed, copiedAt }, now = Date.now()) {
  const ages = [copiedAt, Number(feed?.alive_at) || null].filter((t) => Number.isFinite(t)).map((t) => Math.max(0, now - t))
  return ages.length ? Math.max(...ages) : null
}

export function agoText(ms) {
  if (ms == null) return 'never'
  const m = Math.round(ms / 60_000)
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`
}

// One line for the screen: { from: 'mini', state: 'fresh' | 'stale' | 'missing', ageMs, text }.
export function feedStatus(got, now = Date.now()) {
  if (!got?.feed) {
    return { from: 'mini', state: 'missing', ageMs: null, text: "The Mini isn't answering: no GitHub data from it yet on this machine." }
  }
  const ageMs = feedAge(got, now)
  if (ageMs == null || ageMs > STALE_MS) {
    return { from: 'mini', state: 'stale', ageMs, text: `The Mini isn't answering: GitHub data last read from it ${agoText(ageMs)}.` }
  }
  return { from: 'mini', state: 'fresh', ageMs, text: `Read from the Mini, ${agoText(ageMs)}.` }
}

const LIGHT = ['number', 'title', 'url']

// The box's answers. Reads the copy at most once per change of its mtime (O(size of the feed) per change, O(1) else).
export function createFeedSource({ path = FEED_PATH, now = Date.now, read, mtime } = {}) {
  const opts = { ...(read && { read }), ...(mtime && { mtime }) }
  const stat = mtime || ((p) => statSync(p).mtimeMs)
  let cache = null
  let cacheKey = null
  const current = () => {
    let key
    try {
      key = stat(path)
    } catch {
      key = 'none'
    }
    if (cache && key === cacheKey && key !== 'none') return cache
    cache = readFeed(path, opts)
    cacheKey = key
    return cache
  }
  const entry = (repo, kind) => {
    const got = current()
    if (!got.feed) throw new FeedError(feedStatus(got, now()).text)
    const e = got.feed.repos[repo]?.[kind]
    if (!isObj(e) || e.value == null) throw new FeedError(`${repo} isn't in the Mini's GitHub feed yet.`)
    return e
  }
  return {
    // `gh pr list --json ...` as the Mini read it; the light form is the same list cut to number, title, url.
    openPrs(repo, { light = false } = {}) {
      const e = entry(repo, 'prs')
      if (!Array.isArray(e.value)) throw new FeedError(`${repo}'s PR list in the Mini's feed is unreadable.`)
      return light ? e.value.map((p) => Object.fromEntries(LIGHT.map((f) => [f, p?.[f]]))) : e.value
    },
    board(repo) {
      const v = entry(repo, 'board').value
      if (!isObj(v) || !Array.isArray(v.issues) || !Array.isArray(v.prs)) throw new FeedError(`${repo}'s board in the Mini's feed is unreadable.`)
      return { issues: v.issues, prs: v.prs, holdComments: isObj(v.holdComments) ? v.holdComments : {} }
    },
    // When the Mini read this repo's list from GitHub (its clock), for "Last checked"; null when unknown.
    readAt(repo, kind = 'prs') {
      const at = current().feed?.repos?.[repo]?.[kind]?.at
      return Number.isFinite(at) ? at : null
    },
    status: () => feedStatus(current(), now())
  }
}

// What a pull-only node's dashboard runs in place of `gh` for anything the feed doesn't carry: a plain refusal, never a
// call that could end in gh's login prompt.
export async function feedOnlyGh(args = []) {
  throw new FeedError(`Not available on this machine: it reads GitHub only through the Mini (asked: gh ${String(args[0] || '')} ${String(args[1] || '')}).`.replace(/ +\)/, ')'))
}

// The box shows the Mini's PR list but never acts on it (ADR 0069: it runs untrusted code). Approve, Deny and send-back
// refuse here whatever the renderer sends; the cards show no merge controls (canMerge false).
export const PULL_ONLY_ACTION = 'Approve, Deny and send-back happen on a Mac: this machine only shows what the Mini sees (ADR 0069).'
export function assertActsHere(pullOnly) {
  if (pullOnly) throw Object.assign(new Error(PULL_ONLY_ACTION), { code: 'PULL_ONLY' })
}
export const canMergeHere = (pullOnly, allowed) => !pullOnly && !!allowed

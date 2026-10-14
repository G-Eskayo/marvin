import { readFileSync, readdirSync, existsSync, statSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { HEALTH_STATUS_PATH } from './health.js'

// The boot sequence's data (#431, design in docs/design/celestial-navigation on #428). Every status the boot
// shows comes from here, built from files that already exist -- nothing is decorative. The verdict banner says
// ALL SYSTEMS NOMINAL only with evidence: health_checks says green, every check is green, and the snapshot is fresh.

export const STALE_MINUTES = 20 // health_checks.py runs every 15 minutes (ADR 0033)

const LEVELS = new Set(['green', 'yellow', 'red'])
const RANK = { green: 0, yellow: 1, red: 2 }
const level = (s) => (LEVELS.has(s) ? s : 'yellow') // unknown severity is a warning, never green
const worst = (levels) => (levels.length ? levels.reduce((a, b) => (RANK[b] > RANK[a] ? b : a)) : 'yellow')
const up = (s) => String(s ?? '').toUpperCase()
// Where a summary line leads when clicked in the boot (#433): the exact Health check behind it, or Health itself.
const HEALTH = { tab: 'health' }
const onCheck = (c) => (c?.id ? { tab: 'health', check: c.id } : HEALTH)

export const DEFAULT_BOOT_PATHS = {
  healthPath: HEALTH_STATUS_PATH,
  memoryDir: path.join(homedir(), '.claude', 'projects', '-Users-gileskayo', 'memory'),
  commandsDir: path.join(homedir(), '.claude', 'commands'),
  handoffsDir: path.join(homedir(), '.claude', 'handoffs')
}

function readHealth(healthPath) {
  try {
    const h = JSON.parse(readFileSync(healthPath, 'utf-8'))
    if (!h || typeof h !== 'object' || !Array.isArray(h.checks)) return null
    const checks = h.checks.map((c) =>
      c && typeof c === 'object'
        ? { id: String(c.id ?? ''), label: String(c.label ?? c.id ?? 'unknown check'), severity: level(c.severity), detail: String(c.detail ?? '') }
        : { id: '', label: 'unreadable check', severity: 'yellow', detail: '' }
    )
    return { overall: h.overall, generatedAt: h.generated_at ? new Date(h.generated_at) : null, checks }
  } catch {
    return null
  }
}

function syncLine(checks) {
  const sync = checks.filter((c) => c.id.startsWith('repo:sync:~/.claude') || c.id.startsWith('sync:stuck') || c.id === 'repo:integrity:~/.claude')
  if (!sync.length) return { chip: 'SYNC', level: 'yellow', text: 'MEMORY SYNC · UNKNOWN', target: HEALTH }
  const lvl = worst(sync.map((c) => c.severity))
  const bad = sync.find((c) => c.severity === lvl && lvl !== 'green')
  return { chip: 'SYNC', level: lvl, text: 'MEMORY SYNC · MBP ⇄ MINI' + (bad ? ' · ' + up(bad.label) : ''), target: onCheck(bad ?? sync[0]) }
}

function memoryLine({ memoryDir, commandsDir }) {
  let skills = 0
  try { skills = readdirSync(commandsDir).filter((f) => f.endsWith('.md')).length } catch { /* no commands dir: 0 */ }
  const indexPath = path.join(memoryDir, 'MEMORY.md')
  if (!existsSync(indexPath)) return { chip: 'WARN', level: 'yellow', text: `MEMORY INDEX MISSING · ${skills} SKILLS WIRED` }
  const links = [...readFileSync(indexPath, 'utf-8').matchAll(/\]\(([^)]+\.md)\)/g)].map((m) => m[1])
  const broken = links.filter((l) => !existsSync(path.join(memoryDir, l))).length
  const text = `${links.length} MEMORIES CHARTED · ${skills} SKILLS WIRED`
  return broken
    ? { chip: 'WARN', level: 'yellow', text: `${text} · ${broken} BROKEN LINK${broken > 1 ? 'S' : ''}` }
    : { chip: 'OK', level: 'green', text }
}

function miniReason(c) {
  const pct = c.detail.match(/\((\d+)%\)/)
  if (c.id.startsWith('disk:space') && pct) return `DISK ${pct[1]}% FREE`
  if (c.id.startsWith('jobs:exit')) return `${(c.detail.match(/exit \d+/g) || []).length} JOBS FAILED`
  return up(c.detail.split(/ -- |; |:/)[0]).slice(0, 40) || up(c.label)
}

function miniLine(checks) {
  const keys = checks.filter((c) => ['machine:mac-mini-1', 'disk:space@mac-mini-1', 'jobs:exit@mac-mini-1'].includes(c.id))
  if (!keys.length) return { chip: 'LINK', level: 'yellow', text: 'MAC-MINI · UNKNOWN', target: HEALTH }
  const lvl = worst(keys.map((c) => c.severity))
  const reason = keys.find((c) => c.severity === lvl && lvl !== 'green')
  return { chip: 'LINK', level: lvl, text: 'MAC-MINI · ' + (reason ? miniReason(reason) : 'NOMINAL'), target: onCheck(reason ?? keys[0]) }
}

function handoffLine(handoffsDir) {
  let newest = null
  try {
    for (const f of readdirSync(handoffsDir)) {
      if (!/^handoff-.*\.md$/.test(f)) continue
      const m = statSync(path.join(handoffsDir, f)).mtimeMs
      if (!newest || m > newest.m) newest = { f, m }
    }
  } catch { /* no handoffs dir */ }
  if (!newest) return { chip: 'PLOT', level: 'yellow', text: 'HANDOFF · NONE' }
  const m = newest.f.replace(/\.md$/, '').match(/^handoff-(\d{4}-\d{2}-\d{2})(?:-\d{2}-\d{2})?-?(.*)$/)
  const name = m ? m[1] + (m[2] ? ' · ' + m[2].replace(/-/g, ' ') : '') : newest.f
  return { chip: 'PLOT', level: 'lock', text: ('HANDOFF · ' + up(name)).slice(0, 54) }
}

function testLine(checks) {
  const t = checks.find((c) => c.id === 'main:green')
  if (!t) return { chip: 'TEST', level: 'yellow', text: 'TESTS · UNKNOWN', target: HEALTH }
  const counts = t.detail.match(/\d+ (?:passed|failed|skipped|errors?)/g) || []
  return { chip: 'TEST', level: t.severity, text: 'TESTS · ' + (counts.length ? up(counts.join(' · ')) : up(t.detail).slice(0, 40)), target: onCheck(t) }
}

function verdictOf(health, counts, ageMin) {
  if (!health || !counts.total) return { nominal: false, tone: 'unknown', text: 'HEALTH UNKNOWN · OPEN HEALTH' }
  const parts = [counts.red && `${counts.red} CRITICAL`, counts.yellow && `${counts.yellow} WARNING${counts.yellow > 1 ? 'S' : ''}`].filter(Boolean)
  if (parts.length) return { nominal: false, tone: 'issues', text: parts.join(' · ') + ' · OPEN HEALTH' }
  const fresh = ageMin !== null && ageMin <= STALE_MINUTES
  if (health.overall !== 'green' || !fresh) return { nominal: false, tone: 'unknown', text: (fresh ? 'HEALTH UNCONFIRMED' : 'HEALTH STALE') + ' · OPEN HEALTH' }
  return { nominal: true, tone: 'nominal', text: 'ALL SYSTEMS NOMINAL' }
}

export function buildBootData(opts = {}) {
  const p = { ...DEFAULT_BOOT_PATHS, ...opts }
  const now = opts.now ?? new Date()
  const health = readHealth(p.healthPath)
  const checks = health?.checks ?? []
  const ageMin = health?.generatedAt && !isNaN(health.generatedAt) ? Math.floor((now - health.generatedAt) / 60_000) : null

  const counts = { green: 0, yellow: 0, red: 0, total: checks.length }
  for (const c of checks) counts[c.severity]++

  const lines = [
    { chip: 'LOCK', level: 'lock', text: 'ORIGIN · MARVIN' },
    syncLine(checks),
    memoryLine(p),
    miniLine(checks),
    handoffLine(p.handoffsDir),
    testLine(checks)
  ]
  if (health && (ageMin === null || ageMin > STALE_MINUTES)) {
    lines.push({ chip: 'STALE', level: 'yellow', text: ageMin === null ? 'HEALTH SNAPSHOT UNDATED' : `HEALTH SNAPSHOT ${ageMin} MIN OLD`, target: HEALTH })
  }
  return {
    generatedAt: now.toISOString(),
    healthAt: health?.generatedAt && !isNaN(health.generatedAt) ? health.generatedAt.toISOString() : null,
    counts,
    verdict: verdictOf(health, counts, ageMin),
    lines,
    feed: checks.map((c) => ({ label: c.label, level: c.severity }))
  }
}

// Once per app launch: the first window load gets the boot, reloads (Cmd-R) don't.
export function createBootGate() {
  let shown = false
  return () => {
    if (shown) return false
    shown = true
    return true
  }
}

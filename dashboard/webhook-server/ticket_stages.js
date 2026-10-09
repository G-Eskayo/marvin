import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync, renameSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { resolveDeviceId } from '../electron/main/device_identity.js'

// Node-side mirror of ~/.agents/lib/ticket_stages.py -- same file format,
// same path convention (~/.claude/logs/ticket-stages/<owner>__<repo>-<n>.json), so one
// ticket's timeline covers its whole life across both languages: planning/
// executing/verifying happen in Python (sandbox_orchestration.py), the
// merge gate's rebase/test/merge/rebuild stages happen here in Node
// (webhook-server, where mergePr() already runs).
export const STAGES_DIR = path.join(homedir(), '.claude', 'logs', 'ticket-stages')

const VALID_STAGES = new Set(['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'versioning', 'rebuilding', 'done'])
const VALID_STATUSES = new Set(['started', 'passed', 'failed'])

const MARVIN_REPO = 'G-Eskayo/marvin'
// Keys are lowercased, so the owner's real spelling is restored from here when a key is read back.
const KNOWN_OWNERS = { 'g-eskayo': 'G-Eskayo' }

const isMarvin = (repo) => !repo || repo.toLowerCase() === MARVIN_REPO.toLowerCase()

// `<owner>__<repo>-<n>`, lowercased (#216, mirrors lib/ticket_stages.py's stage_key): #7 in clarity-captions is
// not #7 in marvin, and `__` keeps the key readable back even though the owner itself contains a hyphen.
export function stageKey(repo, ticketNumber) {
  const [owner, name] = (repo || MARVIN_REPO).toLowerCase().split('/')
  return `${owner}__${name}-${ticketNumber}`
}

// The inverse of stageKey, plus marvin's old bare-number files. null for anything else.
export function parseStageKey(stem) {
  if (/^\d+$/.test(stem)) return { repo: MARVIN_REPO, number: parseInt(stem, 10) }
  const m = stem.match(/^(.+?)__(.+)-(\d+)$/)
  if (!m) return null
  const repo = `${KNOWN_OWNERS[m[1]] || m[1]}/${m[2]}`
  return { repo: isMarvin(repo) ? MARVIN_REPO : repo, number: parseInt(m[3], 10) }
}

function stageFile(ticketNumber, dir = STAGES_DIR, repo = null) {
  return path.join(dir, `${stageKey(repo, ticketNumber)}.json`)
}

// marvin's tickets used to be saved by bare number; until migrate_ticket_stages.py has run, read those too.
function legacyFile(ticketNumber, dir, repo) {
  return isMarvin(repo) ? path.join(dir, `${ticketNumber}.json`) : null
}

function trackedFiles(dir) {
  if (!existsSync(dir)) return []
  return readdirSync(dir)
    .filter((name) => name.endsWith('.json'))
    .map((name) => parseStageKey(name.slice(0, -'.json'.length)))
    .filter(Boolean)
}

export function listTrackedTickets(dir = STAGES_DIR, repo = null) {
  const want = (isMarvin(repo) ? MARVIN_REPO : repo).toLowerCase()
  const numbers = trackedFiles(dir).filter((t) => t.repo.toLowerCase() === want).map((t) => t.number)
  return [...new Set(numbers)].sort((a, b) => a - b)
}

// Every tracked ticket in every project: [{ repo, number }].
export function listAllTrackedTickets(dir = STAGES_DIR) {
  const seen = new Map(trackedFiles(dir).map((t) => [`${t.repo}#${t.number}`, t]))
  return [...seen.values()].sort((a, b) => a.repo.localeCompare(b.repo) || a.number - b.number)
}

export function readStages(ticketNumber, dir = STAGES_DIR, repo = null) {
  let file = stageFile(ticketNumber, dir, repo)
  if (!existsSync(file)) file = legacyFile(ticketNumber, dir, repo)
  if (!file || !existsSync(file)) return []
  try {
    return JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return []
  }
}

export function recordStage(ticketNumber, stage, status, detail = '', { machine, costUsd = null, title = null, dir = STAGES_DIR, resolveId = resolveDeviceId, repo = null } = {}) {
  if (!VALID_STAGES.has(stage)) {
    throw new Error(`unknown stage: ${stage} (expected one of ${[...VALID_STAGES].sort().join(', ')})`)
  }
  if (!VALID_STATUSES.has(status)) {
    throw new Error(`unknown status: ${status} (expected one of ${[...VALID_STATUSES].sort().join(', ')})`)
  }

  const event = {
    stage,
    status,
    detail,
    timestamp: new Date().toISOString(),
    machine: machine || resolveId() || 'unknown',
    cost_usd: costUsd,
    // Found live 2026-10-01: a bare ticket number is opaque in any UI --
    // Python's claim-time event is the usual source of truth for this
    // (ticket_pipeline.py already has the GitHub title there); mergePr()
    // can also pass it through from the PR's linked-ticket fetch when
    // available.
    title
  }
  mkdirSync(dir, { recursive: true })
  const legacy = legacyFile(ticketNumber, dir, repo)
  if (legacy && existsSync(legacy) && !existsSync(stageFile(ticketNumber, dir, repo))) renameSync(legacy, stageFile(ticketNumber, dir, repo))
  const events = readStages(ticketNumber, dir, repo)
  events.push(event)
  writeFileSync(stageFile(ticketNumber, dir, repo), JSON.stringify(events, null, 2))
  return event
}

import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { resolveDeviceId } from '../electron/main/device_identity.js'

// Node-side mirror of ~/.agents/lib/ticket_stages.py -- same file format,
// same path convention (~/.claude/logs/ticket-stages/<n>.json), so one
// ticket's timeline covers its whole life across both languages: planning/
// executing/verifying happen in Python (sandbox_orchestration.py), the
// merge gate's rebase/test/merge/rebuild stages happen here in Node
// (webhook-server, where mergePr() already runs).
export const STAGES_DIR = path.join(homedir(), '.claude', 'logs', 'ticket-stages')

const VALID_STAGES = new Set(['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'rebuilding', 'done'])
const VALID_STATUSES = new Set(['started', 'passed', 'failed'])

const MARVIN_REPO = 'G-Eskayo/marvin'

// marvin's tickets keep their plain number; another project's ticket is `<repo>-<n>`, because #7 in
// clarity-captions is not #7 in marvin (mirrors lib/ticket_stages.py).
function stageFile(ticketNumber, dir = STAGES_DIR, repo = null) {
  if (repo && repo !== MARVIN_REPO) return path.join(dir, `${repo.split('/').pop().toLowerCase()}-${ticketNumber}.json`)
  return path.join(dir, `${ticketNumber}.json`)
}

export function listTrackedTickets(dir = STAGES_DIR, repo = null) {
  if (!existsSync(dir)) return []
  const prefix = repo && repo !== MARVIN_REPO ? `${repo.split('/').pop().toLowerCase()}-` : null
  return readdirSync(dir)
    .filter((name) => name.endsWith('.json'))
    .map((name) => name.replace('.json', ''))
    .filter((stem) => (prefix ? stem.startsWith(prefix) : true))
    .map((stem) => (prefix ? stem.slice(prefix.length) : stem))
    .filter((stem) => /^\d+$/.test(stem))
    .map((stem) => parseInt(stem, 10))
    .sort((a, b) => a - b)
}

export function readStages(ticketNumber, dir = STAGES_DIR, repo = null) {
  const file = stageFile(ticketNumber, dir, repo)
  if (!existsSync(file)) return []
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
  const events = readStages(ticketNumber, dir, repo)
  events.push(event)
  writeFileSync(stageFile(ticketNumber, dir, repo), JSON.stringify(events, null, 2))
  return event
}

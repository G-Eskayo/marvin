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

function stageFile(ticketNumber, dir = STAGES_DIR) {
  return path.join(dir, `${ticketNumber}.json`)
}

export function listTrackedTickets(dir = STAGES_DIR) {
  if (!existsSync(dir)) return []
  return readdirSync(dir)
    .filter((name) => name.endsWith('.json'))
    .map((name) => parseInt(name.replace('.json', ''), 10))
    .filter((n) => Number.isInteger(n))
    .sort((a, b) => a - b)
}

export function readStages(ticketNumber, dir = STAGES_DIR) {
  const file = stageFile(ticketNumber, dir)
  if (!existsSync(file)) return []
  try {
    return JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return []
  }
}

export function recordStage(ticketNumber, stage, status, detail = '', { machine, costUsd = null, dir = STAGES_DIR, resolveId = resolveDeviceId } = {}) {
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
    cost_usd: costUsd
  }
  mkdirSync(dir, { recursive: true })
  const events = readStages(ticketNumber, dir)
  events.push(event)
  writeFileSync(stageFile(ticketNumber, dir), JSON.stringify(events, null, 2))
  return event
}

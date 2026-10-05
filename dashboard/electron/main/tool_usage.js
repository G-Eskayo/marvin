import { readFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Reads the scan lib/tool_usage.py writes from the Claude Code transcripts (which tools and skills
// get called, when, how often, and how often it goes wrong).
export const TOOL_USAGE_PATH = path.join(homedir(), '.claude', 'logs', 'tool-usage.json')
export const MAX_AGE_MS = 10 * 60 * 1000

export function readToolUsage(file = TOOL_USAGE_PATH) {
  try {
    const data = JSON.parse(readFileSync(file, 'utf-8'))
    return Array.isArray(data.tools) ? data : null
  } catch {
    return null
  }
}

export function isStale(usage, maxAgeMs = MAX_AGE_MS) {
  const t = Date.parse(usage?.generated_at)
  return !Number.isFinite(t) || Date.now() - t > maxAgeMs
}

// "Failed" = it errored or was an invalid call. Rejected (Gil said no) and interrupted are not the tool's fault.
export const failureRate = (r) => (r.calls ? (r.error + r.invalid) / r.calls : 0)

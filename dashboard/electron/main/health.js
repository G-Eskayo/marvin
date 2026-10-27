import { readFileSync, existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Must run via the venv interpreter, not bare `python3` -- a bare
// interpreter silently lacks chromadb/requests and every check that needs
// them degrades without an obvious error (see MARVIN venv interpreter
// memory note).
const VENV_PYTHON = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const HEALTH_CHECKS_SCRIPT = path.join(homedir(), '.agents', 'lib', 'health_checks.py')

export async function runHealthCheckNow(execFileAsync) {
  await execFileAsync(VENV_PYTHON, [HEALTH_CHECKS_SCRIPT], { timeout: 60_000 })
}

// marvin#691: the Health drill-down's "Rebuild graph now" runs the same refresh the git hooks run (one writer), then
// re-runs the checks so the card shows the result. A failure is returned, never swallowed: the card shows it too.
const AGENTS_REPO = path.join(homedir(), '.agents')
const GRAPHIFY_FRESHNESS_SCRIPT = path.join(AGENTS_REPO, 'lib', 'graphify_freshness.py')

export async function rebuildCodeGraph(execFileAsync) {
  let result
  try {
    const { stdout } = await execFileAsync(VENV_PYTHON, [GRAPHIFY_FRESHNESS_SCRIPT, 'refresh', AGENTS_REPO], { timeout: 900_000 })
    result = { ok: true, output: String(stdout || '') }
  } catch (err) {
    result = { ok: false, output: String(err.stdout || err.stderr || err.message) }
  }
  await runHealthCheckNow(execFileAsync)
  return result
}

// health_checks.py's own output file (ADR 0033) -- a scheduled launchd job
// (com.marvin.health-check, every 15 minutes) writes this; the dashboard is
// a read-only viewer onto it, same ownership split as metrics.js onto
// metrics_registry.py. Local-machine only, same scoping reasoning as
// dispatch_status.js -- the other machine's health needs its own scheduled
// job writing its own file, not an SSH read from here.
export const HEALTH_STATUS_PATH = path.join(homedir(), '.claude', 'logs', 'health-status.json')

const EMPTY_STATUS = { generated_at: null, overall: 'grey', coverage: null, anomaly: null, checks: [] }

export function readHealthStatus(statusPath = HEALTH_STATUS_PATH) {
  if (!existsSync(statusPath)) return EMPTY_STATUS
  try {
    return JSON.parse(readFileSync(statusPath, 'utf-8'))
  } catch {
    return EMPTY_STATUS
  }
}

import { readdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { listJobs } from './jobs.js'

// Every autonomous agent on this machine, for the Health tab: what launchd knows (schedule,
// running now, last exit) joined with what the agent reports about itself (lib/job_events.py run
// log: current step, recent runs). Agents that don't report yet still appear, honestly marked.
const execFileP = promisify(execFile)
const AGENTS_DIR = path.join(homedir(), 'Library', 'LaunchAgents')
const MINE = /^com\.(marvin|giles|gileskayo)\..+\.plist$/

const pad = (n) => String(n ?? 0).padStart(2, '0')

export function describeSchedule(p) {
  if (p.StartInterval) {
    const m = Math.round(p.StartInterval / 60)
    return m === 60 ? 'every hour' : m > 60 && m % 60 === 0 ? `every ${m / 60} hours` : `every ${m} min`
  }
  if (p.StartCalendarInterval) {
    const c = Array.isArray(p.StartCalendarInterval) ? p.StartCalendarInterval[0] : p.StartCalendarInterval
    return `daily at ${pad(c.Hour)}:${pad(c.Minute)}`
  }
  if (p.KeepAlive) return 'always on'
  if (p.RunAtLoad) return 'at login'
  return 'on demand'
}

export function parseLaunchctlList(out) {
  const res = {}
  for (const line of out.split('\n').slice(1)) {
    const [pid, status, label] = line.split('\t')
    if (label) res[label.trim()] = { pid: pid === '-' ? null : Number(pid), status: Number(status) }
  }
  return res
}

const idOf = (label) => label.split('.').slice(2).join('.')
const RANK = { failed: 0, crashed: 0, stopped: 0, running: 1, idle: 2, never: 3 }

export function buildAgents({ plists, launchctl, jobs }) {
  const byJob = Object.fromEntries(jobs.map((j) => [j.job, j]))
  const agents = plists.map((p) => {
    const id = idOf(p.label)
    const ls = launchctl[p.label] || { pid: null, status: null }
    const service = !!p.KeepAlive
    const job = byJob[id] || null
    let status
    if (ls.pid) status = 'running'
    else if (service) status = 'stopped'
    else if (job) status = job.status === 'running' ? 'crashed' : job.status // launchd says not running, log says running: it died
    else status = ls.status && ls.status !== 0 ? 'failed' : 'idle'
    return {
      id,
      label: job?.label || id,
      kind: service ? 'service' : 'scheduled',
      schedule: describeSchedule(p),
      pid: ls.pid,
      lastExit: ls.status,
      running: !!ls.pid,
      reporting: !!job,
      status,
      job
    }
  })
  // Run logs with no launchd agent of their own (project-catalog runs inside the hourly scan,
  // dashboard-rebuild inside the sync chain) are still agents' work and must not vanish.
  const known = new Set(agents.map((a) => a.id))
  for (const j of jobs) {
    if (known.has(j.job)) continue
    agents.push({ id: j.job, label: j.label, kind: 'job', schedule: 'runs inside another agent', pid: null, lastExit: null, running: j.status === 'running', reporting: true, status: j.status, job: j })
  }
  return agents.sort((a, b) => RANK[a.status] - RANK[b.status] || a.id.localeCompare(b.id))
}

async function readPlists(dir, run) {
  const files = readdirSync(dir).filter((n) => MINE.test(n))
  const out = []
  for (const f of files) {
    try {
      const json = await run('/usr/bin/plutil', ['-convert', 'json', '-o', '-', path.join(dir, f)])
      const p = JSON.parse(json)
      if (p.Label) out.push({ ...p, label: p.Label })
    } catch {
      // unreadable plist: skip it
    }
  }
  return out
}

export async function listAgents({ dir = AGENTS_DIR, run = async (c, a) => (await execFileP(c, a)).stdout, jobs = listJobs() } = {}) {
  let plists = []
  try {
    plists = await readPlists(dir, run)
  } catch {
    // no LaunchAgents folder
  }
  let launchctl = {}
  try {
    launchctl = parseLaunchctlList(await run('/bin/launchctl', ['list']))
  } catch {
    // leave unknown rather than guess
  }
  return buildAgents({ plists, launchctl, jobs })
}

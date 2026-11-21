import { appendFileSync, mkdirSync, statSync, readFileSync, writeFileSync } from 'fs'
import { homedir } from 'os'
import { join, dirname } from 'path'

// CPU/GPU process sampling for mac-mini-2012 diagnostics: app.getAppMetrics() on 5s interval,
// reusing error_log.js's bounded-append pattern. AC#1 and AC#2.
export const CPU_SAMPLE_LOG = join(homedir(), '.claude', 'logs', 'cpu-samples.jsonl')

// CPU sampler: app.getAppMetrics() every 5s, bounded log reusing error_log.js pattern.
export function createCpuSampler(app, { appendLog, appName = 'unknown', maxBytes = 10 * 1024 * 1024, keepLines = 10000 } = {}) {
  const sample = () => {
    try {
      const metrics = app.getAppMetrics()
      if (!Array.isArray(metrics)) return

      const t = new Date().toISOString()
      for (const m of metrics) {
        if (!m || typeof m !== 'object') continue
        const cpu = m.cpu?.percentCPUUsage
        if (typeof cpu !== 'number') continue

        const entry = {
          app: appName,
          t,
          type: String(m.type || 'unknown').slice(0, 50),
          pid: Number(m.pid) || 0,
          cpu: Math.round(cpu * 100) / 100
        }

        try {
          appendLog(JSON.stringify(entry) + '\n')
        } catch {
          // appendLog must not break sampling
        }
      }
    } catch {
      // getAppMetrics failures must not break the app
    }
  }

  let intervalId = null

  const start = () => {
    if (intervalId !== null) return // singleton guard
    intervalId = setInterval(sample, 5000)
  }

  const stop = () => {
    if (intervalId !== null) {
      clearInterval(intervalId)
      intervalId = null
    }
  }

  return { sample, start, stop }
}

// Bounded log append: reuses error_log.js's shape (appendFileSync + trim oldest when size > maxBytes).
export function appendCpuSampleLog(entry, { file = CPU_SAMPLE_LOG, maxBytes = 10 * 1024 * 1024, keepLines = 10000 } = {}) {
  try {
    mkdirSync(dirname(file), { recursive: true })
    appendFileSync(file, entry)

    let size = 0
    try {
      size = statSync(file).size
    } catch {
      size = 0
    }

    if (size > maxBytes) {
      const lines = readFileSync(file, 'utf-8').split('\n').filter(Boolean)
      writeFileSync(file, lines.slice(-keepLines).join('\n') + '\n')
    }
  } catch {
    // logging must never break the app
  }
}

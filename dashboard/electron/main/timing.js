import { appendFileSync, mkdirSync, statSync, renameSync } from 'fs'
import os from 'os'
import path from 'path'

// How long every dashboard call takes (#236). Gil: "the dashboard is pretty slow across the board". Rather than guess,
// every IPC handler (Electron main) and every webhook route is timed into one JSON-lines log, and rankTimings turns it
// into "where the time goes" (dashboard/scripts/timing_report.mjs). Kept on permanently: it costs one appended line
// per call and is the signal a Health check can use. Fail-soft: timing must never break or slow the call it measures.

export const TIMING_LOG = path.join(os.homedir(), '.claude', 'logs', 'dashboard-timing.jsonl')
const MAX_BYTES = 5 * 1024 * 1024

export function appendTiming(entry, file = TIMING_LOG) {
  try {
    mkdirSync(path.dirname(file), { recursive: true })
    try {
      if (statSync(file).size > MAX_BYTES) renameSync(file, `${file}.1`)
    } catch { /* no file yet */ }
    appendFileSync(file, JSON.stringify({ t: new Date().toISOString(), machine: os.hostname(), ...entry }) + '\n')
  } catch { /* fail-soft */ }
}

const defaults = { record: appendTiming, now: () => performance.now() }

function safeRecord(record, entry) {
  try { record(entry) } catch { /* fail-soft */ }
}

export function timed(side, name, fn, { record = defaults.record, now = defaults.now } = {}) {
  return async (...args) => {
    const start = now()
    try {
      const result = await fn(...args)
      safeRecord(record, { side, name, ms: Math.round(now() - start), ok: true })
      return result
    } catch (err) {
      safeRecord(record, { side, name, ms: Math.round(now() - start), ok: false })
      throw err
    }
  }
}

// Call once, before any handler is registered: every later ipcMain.handle(channel, fn) is timed under its channel name.
export function instrumentIpc(ipcMain, opts = {}) {
  const handle = ipcMain.handle.bind(ipcMain)
  ipcMain.handle = (channel, fn) => handle(channel, timed('ipc', channel, fn, opts))
}

// For the webhook's request handler: records `METHOD /path` when the response is finished.
export function timeRequest(req, res, { record = defaults.record, now = defaults.now } = {}) {
  const start = now()
  const name = `${req.method} ${String(req.url || '').split('?')[0]}`
  res.once('finish', () => safeRecord(record, { side: 'webhook', name, ms: Math.round(now() - start), ok: res.statusCode < 400 }))
}

const pct = (sorted, p) => sorted[Math.max(0, Math.ceil(p * sorted.length) - 1)]

// [{name, side, ms}] → per call: count, totalMs, p50, p95, max, failures; biggest total first.
export function rankTimings(rows) {
  const by = new Map()
  for (const r of rows) {
    const key = `${r.side} ${r.name}`
    if (!by.has(key)) by.set(key, { name: r.name, side: r.side, ms: [], failures: 0 })
    const g = by.get(key)
    g.ms.push(r.ms)
    if (r.ok === false) g.failures++
  }
  return [...by.values()].map((g) => {
    const s = [...g.ms].sort((a, b) => a - b)
    return { name: g.name, side: g.side, count: s.length, totalMs: s.reduce((a, b) => a + b, 0), p50: pct(s, 0.5), p95: pct(s, 0.95), max: s[s.length - 1], failures: g.failures }
  }).sort((a, b) => b.totalMs - a.totalMs)
}

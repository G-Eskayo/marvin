// Where the dashboard's time goes (#236): ranks ~/.claude/logs/dashboard-timing.jsonl by total time.
// Usage: node scripts/timing_report.mjs [hours=24] [log path]
import { readFileSync, existsSync } from 'node:fs'
import { rankTimings, TIMING_LOG } from '../electron/main/timing.js'

const hours = Number(process.argv[2] || 24)
const file = process.argv[3] || TIMING_LOG
if (!existsSync(file)) {
  console.error(`no timing log at ${file} yet: use the dashboard first`)
  process.exit(1)
}
const since = Date.now() - hours * 3600 * 1000
const rows = readFileSync(file, 'utf-8').split('\n').filter(Boolean)
  .map((l) => { try { return JSON.parse(l) } catch { return null } })
  .filter((r) => r && Date.parse(r.t) >= since)
const ranked = rankTimings(rows)
const pad = (v, n) => String(v).padStart(n)
console.log(`${rows.length} calls in the last ${hours} h\n`)
console.log(`${'total s'.padStart(8)} ${'count'.padStart(6)} ${'p50 ms'.padStart(7)} ${'p95 ms'.padStart(7)} ${'max ms'.padStart(7)} ${'fail'.padStart(5)}  call`)
for (const r of ranked.slice(0, 25)) {
  console.log(`${pad((r.totalMs / 1000).toFixed(1), 8)} ${pad(r.count, 6)} ${pad(r.p50, 7)} ${pad(r.p95, 7)} ${pad(r.max, 7)} ${pad(r.failures, 5)}  ${r.side} ${r.name}`)
}

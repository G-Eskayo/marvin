import { closeSync, fstatSync, openSync, readSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// The Vitals verdict line's budget (marvin#873, refresh 2026-11-04 item 2): the Claude plan's own meters, the last row
// lib/plan_usage.py wrote to plan-usage.jsonl (it writes only when a meter changes, so the last row is the current
// reading). Only the file's tail is read. No row is null, which the tab shows as "not enough data", never 0%.
export const PLAN_USAGE_PATH = path.join(homedir(), '.claude', 'logs', 'plan-usage.jsonl')
const TAIL_BYTES = 16 * 1024

export function readPlanMeter(file = PLAN_USAGE_PATH) {
  let fd
  try {
    fd = openSync(file, 'r')
    const size = fstatSync(fd).size
    const len = Math.min(size, TAIL_BYTES)
    const buf = Buffer.alloc(len)
    readSync(fd, buf, 0, len, size - len)
    const lines = buf.toString('utf8').split('\n')
    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        const row = JSON.parse(lines[i])
        if (row && typeof row === 'object' && !Array.isArray(row) && (row.five_hour || row.seven_day)) return row
      } catch { /* a torn or partial line: try the one before */ }
    }
    return null
  } catch {
    return null
  } finally {
    if (fd !== undefined) try { closeSync(fd) } catch { /* already closed */ }
  }
}

import { readFileSync, writeFileSync, appendFileSync, mkdirSync, existsSync, statSync, openSync, readSync, closeSync, renameSync } from 'fs'
import os from 'os'
import path from 'path'
import { execFileSync } from 'child_process'
import { emptyProgress, applyMergeEvent, MERGE_STAGES, machineLabel } from '../src/lib/merge_progress.js'

// The merge gate's side of marvin#568: what each merge is doing, told as it happens.
//   - createMergeTracker: one per Approve. Numbers each stage event, folds it with the same reducer the dashboard
//     uses, sends it on (the approve response's stream and the local refresh ping), logs each change to
//     dashboard-webhook.log, and keeps the in-flight record that a restart turns into "interrupted".
//   - in-flight store: ~/.claude/logs/merge-inflight.json, written on each stage change (about 8 per merge).
//   - durations: ~/.claude/logs/gate-run-durations.jsonl, one real line per finished merge, read back for the
//     "usually about 3 min" estimate. Bounded: only its tail is read, and it is trimmed as it grows.
//   - machine load and the gate's load-aware time limit.
// Paths are worked out from os.homedir() at call time, so tests with a temp HOME never touch the real logs.

const logsDir = () => path.join(os.homedir(), '.claude', 'logs')
export const inflightPath = () => path.join(logsDir(), 'merge-inflight.json')
export const durationsPath = () => path.join(logsDir(), 'gate-run-durations.jsonl')

const prLabel = (url) => {
  const m = String(url).match(/github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/)
  return m ? `${m[1]}#${m[2]}` : String(url).slice(0, 120)
}
const clock = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// ---- in-flight merges (survive a restart as "interrupted") ----

function readJson(file, fallback) {
  try { return JSON.parse(readFileSync(file, 'utf-8')) } catch { return fallback }
}
function writeJsonAtomic(file, value) {
  mkdirSync(path.dirname(file), { recursive: true })
  const tmp = `${file}.${process.pid}.tmp`
  writeFileSync(tmp, JSON.stringify(value, null, 2))
  renameSync(tmp, file)
}

export function createInflightStore(file = inflightPath()) {
  const read = () => {
    const v = readJson(file, {})
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
  }
  return {
    set(url, entry) {
      const all = read()
      all[url] = entry
      try { writeJsonAtomic(file, all) } catch { /* the record is a convenience; the merge must not fail on it */ }
    },
    remove(url) {
      const all = read()
      if (!(url in all)) return
      delete all[url]
      try { writeJsonAtomic(file, all) } catch { /* as above */ }
    },
    read
  }
}

// On webhook start: every merge the file still lists was running when the last process died. Each is logged,
// removed, and returned, so index.js can tell an open dashboard straight away ("interrupted", one event each).
export function takeInterruptedMerges(file = inflightPath(), { log = console.log, now = Date.now } = {}) {
  const store = createInflightStore(file)
  const all = store.read()
  const lost = []
  for (const [url, e] of Object.entries(all)) {
    if (typeof url !== 'string' || !url.startsWith('https://github.com/') || !e || typeof e !== 'object') continue
    const stage = MERGE_STAGES.some(([k]) => k === e.stage) ? e.stage : 'queued'
    lost.push({ url, id: e.id ?? null, seq: Number.isFinite(e.seq) ? e.seq : 0, stage, startedAt: e.startedAt ?? null })
    log(`[merge] ${prLabel(url)} interrupted: the webhook restarted while it was at "${stage}"${e.startedAt ? ` (started ${new Date(e.startedAt).toISOString()})` : ''}. Approve again.`)
  }
  if (Object.keys(all).length) {
    try { writeJsonAtomic(file, {}) } catch { /* nothing more to do */ }
  }
  return lost.map((l) => ({ url: l.url, event: { id: l.id, seq: l.seq + 1, stage: l.stage, state: 'failed', interrupted: true, at: now(), detail: 'interrupted: the webhook restarted' } }))
}

// ---- real gate durations ----

const DURATIONS_MAX_BYTES = 256 * 1024
const DURATIONS_KEEP_LINES = 500
const TAIL_BYTES = 64 * 1024

function readTail(file, bytes = TAIL_BYTES) {
  if (!existsSync(file)) return ''
  const size = statSync(file).size
  const len = Math.min(size, bytes)
  const fd = openSync(file, 'r')
  try {
    const buf = Buffer.alloc(len)
    readSync(fd, buf, 0, len, size - len)
    const text = buf.toString('utf-8')
    return size > len ? text.slice(text.indexOf('\n') + 1) : text
  } finally {
    closeSync(fd)
  }
}

export function recordMergeDuration(entry, file = durationsPath()) {
  if (!(entry?.durationMs > 0)) return
  try {
    mkdirSync(path.dirname(file), { recursive: true })
    appendFileSync(file, JSON.stringify({ t: new Date().toISOString(), ...entry }) + '\n')
    if (statSync(file).size > DURATIONS_MAX_BYTES) {
      const lines = readFileSync(file, 'utf-8').split('\n').filter(Boolean).slice(-DURATIONS_KEEP_LINES)
      writeFileSync(file, lines.join('\n') + '\n')
    }
  } catch { /* a missing estimate is fine; a failed merge because of it is not */ }
}

// The median of the last merges of this repo that took the same path (retested or not) and merged. Lines from before
// marvin#568 (no repo, durationMs 0) are ignored. null when there is no history yet.
export function estimateMergeMs(repo, gated, file = durationsPath(), last = 20) {
  let text = ''
  try { text = readTail(file) } catch { return null }
  const ms = text.split('\n').map((l) => { try { return JSON.parse(l) } catch { return null } })
    .filter((e) => e && e.repo === repo && e.gated === !!gated && e.outcome === 'merged' && e.durationMs > 0)
    .slice(-last).map((e) => e.durationMs).sort((a, b) => a - b)
  if (!ms.length) return null
  const mid = Math.floor(ms.length / 2)
  return ms.length % 2 ? ms[mid] : Math.round((ms[mid - 1] + ms[mid]) / 2)
}

// ---- machine load ----

// Long jobs the owner would recognise, by command line; anything else is named by its program.
const KNOWN_JOBS = [[/engine|whisper|speech/i, 'engine test'], [/bench\b|bench\.py|bench\//i, 'bench run'], [/xcodebuild/i, 'app build'], [/pytest|vitest/i, 'another test run']]

export function topProcess(exec = (cmd, args) => execFileSync(cmd, args, { encoding: 'utf-8', timeout: 3000 })) {
  try {
    const lines = exec('/bin/ps', ['-Ao', 'pcpu=,args=', '-r']).split('\n').map((l) => l.trim()).filter(Boolean)
    for (const line of lines.slice(0, 5)) {
      const args = line.replace(/^[\d.]+\s+/, '')
      if (/\bps -Ao\b/.test(args)) continue
      const known = KNOWN_JOBS.find(([re]) => re.test(args))
      return known ? known[1] : path.basename(args.split(/\s+/)[0] || '').slice(0, 40) || null
    }
  } catch { /* unknown */ }
  return null
}

export const BUSY_PER_CORE = 0.7

// { id, load, cores, busy, top }. `top` (one ps call) only when busy, to name what is using the machine.
export function machineLoad({ loadavg = os.loadavg, cpus = () => os.cpus().length, top = topProcess, id = null } = {}) {
  const load = Math.round((loadavg()[0] || 0) * 10) / 10
  const cores = Math.max(1, cpus() || 1)
  const busy = load / cores >= BUSY_PER_CORE
  return { id, load, cores, busy, ...(busy ? { top: top() } : {}) }
}

// The gate's time limit, decided when it runs out (marvin#568; #559 was cut off three times while the Mac mini ran
// an engine test). If the machine is busy and the tests are still producing output, the limit is extended once by
// half, with the reason stated. Otherwise the gate is cut off as before, and the reason says whether the machine was
// busy, so "GATE_INFRA" is never a mystery. Pure.
export const PROGRESS_WINDOW_MS = 5 * 60_000

export function gateExtension({ baseMs, load, lastOutputAt, now }) {
  const where = machineLabel(load?.id)
  const loadText = load ? `load ${load.load} on ${load.cores} cores${load.top ? `, ${load.top} running` : ''}` : 'load unknown'
  const progressing = lastOutputAt != null && now - lastOutputAt < PROGRESS_WINDOW_MS
  if (load?.busy && progressing) {
    const extendMs = Math.round(baseMs / 2)
    return { extendMs, reason: `${where} is busy (${loadText}) and the tests are still making progress, so the time limit was extended by ${Math.round(extendMs / 60_000)} min` }
  }
  return { extendMs: 0, note: load?.busy ? `${where} was busy (${loadText}) and the tests had stopped producing output` : `${where} was not busy (${loadText}), so the tests most likely hung` }
}

// ---- live test counts from the runners' own output ----

// pytest -q ends each line of dots with "[ 42%]"; vitest's default reporter prints one line per finished file
// ("✓ test/x.test.js (5 tests) 12ms", or ❯/× when it failed). Returns a parser fed raw output chunks; it calls
// onCount at most once per 5 points of progress, so a run makes about 20 events, never one per test.
export function createCountParser(runner, { totalFiles = 0, onCount }) {
  let lastBucket = '', done = 0, partial = ''
  const report = (count) => {
    const pct = Math.floor((count.done / count.total) * 100)
    const bucket = `${count.done >= count.total ? 100 : Math.floor(pct / 5)}/${count.total}`
    if (bucket === lastBucket) return
    lastBucket = bucket
    onCount(count)
  }
  return (chunk) => {
    const text = partial + String(chunk)
    const lines = text.split('\n')
    partial = lines.pop() ?? ''
    for (const line of lines) {
      if (runner === 'pytest') {
        const m = line.match(/\[\s*(\d{1,3})%\]\s*$/)
        if (m) report({ done: Math.min(100, Number(m[1])), total: 100, unit: '%' })
      } else if (/^\s*[✓❯×]\s+\S+\.(test|spec)\.[cm]?[jt]sx?\b/.test(line)) {
        done += 1
        // With no known total every file would be "all done"; report every 25th instead, so it stays bounded.
        if (totalFiles > 0) report({ done, total: Math.max(totalFiles, done), unit: 'files' })
        else if (done % 25 === 0) onCount({ done, total: done, unit: 'files' })
      }
    }
  }
}

// ---- the tracker ----

export function createMergeTracker({ url, repo = null, machineId = null, emit = () => {}, log = console.log, inflight = null, measure = null, estimate = null, record = null, now = Date.now, id = null }) {
  const attempt = id || `${now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  const startedAt = now()
  let seq = 0
  let progress = emptyProgress()
  let gated = null
  const label = prLabel(url)

  function event(stage, state, extra = {}) {
    const ev = { id: attempt, seq: seq + 1, stage, state, at: now() }
    if (extra.detail) ev.detail = String(extra.detail).slice(0, 300)
    if (extra.count) ev.count = extra.count
    if (extra.estimateMs) ev.estimateMs = extra.estimateMs
    // The machine is measured where it matters: as the merge starts and as the tests start.
    if (state === 'running' && (stage === 'fetching' || stage === 'tests') && progress.stages[stage]?.state !== 'running' && measure) {
      try { ev.machine = { ...measure(), id: machineId } } catch { /* unknown load */ }
    }
    if (stage === 'fetching' && state === 'done' && typeof extra.gated === 'boolean') {
      gated = extra.gated
      const est = estimate ? estimate(repo, gated) : null
      if (est) ev.estimateMs = est
    }
    const next = applyMergeEvent(progress, ev)
    if (next === progress) return null
    seq = ev.seq
    const before = progress.stages[stage]?.state
    progress = next
    // One log line per stage change (counts are not logged: they would only add noise).
    if (before !== state) {
      const busy = ev.machine?.busy ? ` [${machineLabel(machineId)} busy: load ${ev.machine.load} on ${ev.machine.cores} cores${ev.machine.top ? `, ${ev.machine.top}` : ''}]` : ''
      log(`[merge] ${label} ${stage} ${state}${ev.detail ? `: ${ev.detail.split('\n')[0].slice(0, 200)}` : ''}${busy}`)
    } else if (ev.detail && extra.logDetail) {
      log(`[merge] ${label} ${stage}: ${ev.detail.split('\n')[0].slice(0, 200)}`)
    }
    inflight?.set(url, { id: attempt, seq, stage, startedAt, machine: machineId })
    try { emit(ev) } catch { /* a reader going away never stops the merge */ }
    return ev
  }

  // The stage that is running now (the one a failure belongs to).
  const current = () => {
    const running = MERGE_STAGES.filter(([k]) => progress.stages[k]?.state === 'running').map(([k]) => k)
    return running[running.length - 1] || MERGE_STAGES.find(([k]) => !progress.stages[k])?.[0] || 'queued'
  }

  function end(outcome, detail) {
    inflight?.remove(url)
    const ms = now() - startedAt
    const stages = {}
    for (const [k] of MERGE_STAGES) {
      const s = progress.stages[k]
      if (s?.startedAt != null && s?.endedAt != null) stages[k] = s.endedAt - s.startedAt
    }
    if (record && gated !== null) record({ repo, gated, outcome, durationMs: ms, stages })
    log(`[merge] ${label} finished: ${outcome} after ${clock(ms)}${detail ? ` (${String(detail).split('\n')[0].slice(0, 200)})` : ''}`)
  }

  return {
    id: attempt,
    start(ahead = 0) {
      log(`[merge] ${label} started on ${machineLabel(machineId)}${ahead ? ` (${ahead} merge${ahead === 1 ? '' : 's'} ahead in the queue)` : ''}`)
      return event('queued', 'running', ahead ? { detail: `${ahead} merge${ahead === 1 ? '' : 's'} ahead` } : {})
    },
    // What merge.js calls: progress(stage, state, extra). 'output' is a heartbeat (tests still printing), not an event.
    progress(stage, state, extra) {
      if (state === 'output') return null
      return event(stage, state, extra)
    },
    finish(result) {
      if (result?.merged) {
        event('done', 'done')
        end('merged')
      } else {
        const why = `${result?.code || 'SENT_BACK'}: sent back for rework`
        event(current(), 'failed', { detail: why })
        end('sent back', why)
      }
    },
    fail(body) {
      const why = `${body?.code || 'ERROR'}: ${String(body?.message || body?.error || 'the merge failed').split('\n')[0]}`
      event(current(), 'failed', { detail: why })
      end('refused', why)
    },
    snapshot: () => progress
  }
}

// ---- the approve response as a stream ----

// A caller that sends `Accept: application/x-ndjson` (the dashboard, marvin#568) gets the answer as lines: one
// {type:"progress", event} per stage event as it happens, then one {type:"result", status, body} with exactly what the
// plain JSON response would have said. Everyone else (the phone backend, auto-merge) gets the plain response as before.
// The open connection is the push channel: it reaches the dashboard on whichever Mac clicked, and if this process
// dies mid-merge the connection drops, which the dashboard reads as "interrupted" at once.
export const NDJSON = 'application/x-ndjson'
export const wantsStream = (accept) => String(accept || '').toLowerCase().includes(NDJSON)

export function approveResponder(res, { streaming }) {
  if (streaming) {
    res.writeHead(200, { 'Content-Type': NDJSON, 'Cache-Control': 'no-store' })
    res.on?.('error', () => {}) // the reader went away: the merge carries on
  }
  const line = (v) => JSON.stringify(v) + '\n'
  return {
    event(ev) {
      if (streaming && !res.writableEnded && !res.destroyed) res.write(line({ type: 'progress', event: ev }))
    },
    result(status, body) {
      if (streaming) {
        if (!res.writableEnded) res.end(line({ type: 'result', status, body }))
      } else {
        res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(body))
      }
    }
  }
}

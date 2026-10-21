import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import path from 'path'
import { analyzeSource, scanFiles, checkAllowlist, GUIDANCE, EVIDENCE_SCRIPT } from './polling_guard.js'

// marvin#556: "Triggers over polling" (CONTEXT.md, decided 2026-10-03) enforced, not remembered. #554 added a 90 s
// re-read of PR checks (pendingChecksTtl) although gh_watch.js's ETag change-detector already covered it at zero
// rate-limit cost. Every timer and TTL in the dashboard's source must be listed here with its count and a one-line
// reason; a new one fails until it is moved to a trigger or justified. Shape reused from rules_of_hooks.test.js and
// csp.test.js: the rule reads the real source, and CI (.github/workflows/ci.yml) and the merge gate run it on every PR.
//
// Kinds (see polling_guard.js): interval, timeout-loop, ttl. UI clocks (callback only calls this file's useState
// setters and Date.now) are allowed by rule, never by name, and need no entry.
const TODO_558 = 'TODO: move to trigger, see follow-up #558'
const CHECK_WATCH = 'the #557 check watch: one ETag (conditional) request per PR head with checks running, 304 is free, the same pattern as the change-detector; real push replaces it (#566)'
export const ALLOWLIST = {
  // Renderer. Each reads main-process IPC; GitHub-backed IPC answers from github_state's cache (change-ping driven).
  'src/App.jsx': { interval: [2, 'backstops: MR status dot behind mr.onRefresh push (2 min), Health dot reads the local snapshot (60 s)'] },
  'src/components/ActivityBanner.jsx': { interval: [1, 'backstop 60 s over the local health snapshot file; no network'] },
  'src/components/DeviceColumns.jsx': { interval: [1, 'remote machines have no push channel (ssh status, 15 s, cached 8 s in devices.js)'] },
  'src/components/DispatchStatusBadge.jsx': { interval: [1, TODO_558] },
  'src/components/HealthDashboard.jsx': { interval: [2, 'backstops: agents list behind the agents trigger, view over the local health snapshot (60 s each)'] },
  'src/components/MrReview.jsx': {
    interval: [1, 'backstop 2 min behind mr.onRefresh push; mr:list reads github_state cache, not GitHub'],
    'timeout-loop': [1, TODO_558]
  },
  'src/components/NextUpQueue.jsx': { interval: [1, TODO_558] },
  'src/components/ProjectBoard.jsx': { interval: [1, 'the 60 s backstop + coverage guard CONTEXT.md names (trigger-misses.jsonl)'] },
  'src/components/ResourcesPanel.jsx': { interval: [1, 'resource samples from the 30 s collector files; no trigger exists, no GitHub'] },
  'src/components/TicketAgentsPanel.jsx': { interval: [1, 'backstop 60 s over local ticket-agent state files; no network'] },
  'src/lib/cdp_capture.js': { 'timeout-loop': [3, 'bounded wait for a local Electron CDP port/window to appear; no event exists'] },
  // Main process.
  'electron/main/boards.js': { ttl: [2, 'cache bounds: cross-project 30 min safety net cleared by change pings (#318); evidence 5 min'] },
  'electron/main/devices.js': { ttl: [1, 'read-through cache bound (8 s) on an ssh round-trip; no timer, never triggers a read'] },
  'electron/main/github_state.js': { ttl: [1, 'the cache itself: its 30-min safety lifetime (#557 removed the ttlFor hook)'] },
  'electron/main/index.js': { interval: [1, `starts ${CHECK_WATCH}`] },
  'electron/main/queue.js': { ttl: [1, 'read-through cache bound (60 s) on ticket_queue.py; no timer of its own'] },
  'electron/main/relations_service.js': { ttl: [1, 'read-through cache bound (60 s), invalidated by the board/docs triggers'] },
  'electron/main/rework.js': { ttl: [1, 'read-through cache bound (60 s); index.js calls it through github_state with minInterval'] },
  'electron/main/usage_report.js': { ttl: [1, 'read-through cache bound (60 s) on a local scan + ssh; no GitHub, no timer'] },
  // Servers.
  'webhook-server/gh_watch.js': { interval: [2, 'THE change-detector (one ETag request per repo per ~20 s, 304 is free) and the check watch beside it (#557)'] },
  'webhook-server/index.js': { interval: [1, 'starts the one gh_watch change-detector tick'] },
  'webhook-server/failure.js': { 'timeout-loop': [1, 'withRetry: bounded exponential backoff on a failed call, not a poll for change'] },
  'webhook-server/merge.js': { 'timeout-loop': [1, 'mergeableNow: GitHub computes mergeable lazily with no event; bounded 6 x 5 s'] },
  'mobile-backend/dashboard_gh_api.js': { interval: [1, `starts ${CHECK_WATCH}`] },
  'mobile-backend/pending_actions.js': { 'timeout-loop': [1, 'waits on its own local store for an approval, bounded by the hook timeout; no network'] }
}

const ROOT = path.resolve(__dirname, '..')
const SCANNED = ['src', 'electron', 'webhook-server', 'mobile-backend', 'scripts']
const SOURCE = /\.(c|m)?[jt]sx?$/

function sourceFiles() {
  const files = []
  const walk = (dir) => {
    for (const name of readdirSync(path.join(ROOT, dir))) {
      if (name === 'node_modules' || name === 'out' || name === 'dist' || name === 'test') continue
      const rel = `${dir}/${name}`
      if (statSync(path.join(ROOT, rel)).isDirectory()) walk(rel)
      else if (SOURCE.test(name)) files.push({ path: rel, code: readFileSync(path.join(ROOT, rel), 'utf8') })
    }
  }
  SCANNED.forEach(walk)
  return files
}

const kinds = (code, file) => analyzeSource(code, file).map((f) => f.kind)
const failing = (code, file) => kinds(code, file).filter((k) => k !== 'ui-clock')

describe('the dashboard source keeps to Triggers over polling', () => {
  it('every timer and TTL is a trigger, a UI clock, or allowlisted with its count and a reason', () => {
    const problems = checkAllowlist(scanFiles(sourceFiles()), ALLOWLIST)
    expect(problems, `${problems.join('\n')}\n\n${GUIDANCE}`).toEqual([])
  })

  it('still catches #554\'s pendingChecksTtl, the re-read that started #556 (its code before #557 removed it)', () => {
    const src = `export const PENDING_CHECKS_TTL_MS = 90_000
export function pendingChecksTtl(prs) {
  if (!Array.isArray(prs)) return undefined
  return prs.some((p) => p && ciState(p.statusCheckRollup).state === 'pending') ? PENDING_CHECKS_TTL_MS : undefined
}`
    const problems = checkAllowlist(scanFiles([{ path: 'electron/main/mr_repos.js', code: src }]), {})
    expect(problems.join('\n')).toContain('electron/main/mr_repos.js: ')
  })

  it('evidence scripts may wait in a loop for their local Electron window, but still may not poll on an interval', () => {
    const waits = 'const sleep = (ms) => new Promise((r) => setTimeout(r, ms))\nlet page; for (let i = 0; i < 40 && !page; i++) { page = find(); if (!page) await sleep(250) }'
    expect(checkAllowlist(scanFiles([{ path: 'scripts/new_thing_evidence.mjs', code: waits }]), {})).toEqual([])
    expect(checkAllowlist(scanFiles([{ path: 'scripts/new_thing_evidence.mjs', code: 'setInterval(load, 20_000)' }]), {}).join('\n')).toContain('interval')
    expect(checkAllowlist(scanFiles([{ path: 'scripts/sync_thing.mjs', code: waits }]), {}).join('\n')).toContain('timeout-loop')
    expect(EVIDENCE_SCRIPT.test('scripts/../electron/x_evidence.mjs')).toBe(false)
    expect(EVIDENCE_SCRIPT.test('src/x_evidence.mjs')).toBe(false)
  })

  it('every TODO entry points at an issue', () => {
    for (const [p, k] of Object.entries(ALLOWLIST)) for (const [kind, [, why]] of Object.entries(k)) {
      if (/^TODO/.test(why)) expect(why, `${p} ${kind}`).toMatch(/#\d+/)
    }
  })

  it('scans every source extension, and the scan is not empty', () => {
    const files = sourceFiles()
    expect(files.length).toBeGreaterThan(100)
    expect(files.some((f) => f.path.endsWith('.jsx'))).toBe(true)
  })
})

describe('the guard catches polling however it is written', () => {
  it('a plain setInterval', () => {
    expect(failing('setInterval(load, 60_000)')).toEqual(['interval'])
  })

  it('a renamed alias: const si = setInterval', () => {
    expect(failing('const si = setInterval\nsi(load, 1000)')).toEqual(['interval'])
  })

  it('globalThis / window / bracket access', () => {
    expect(failing('globalThis.setInterval(load, 1000)')).toEqual(['interval'])
    expect(failing("window['setInterval'](load, 1000)")).toEqual(['interval'])
    expect(failing('global.setTimeout(function tick() { load(); global.setTimeout(tick, 9) }, 9)')).toContain('timeout-loop')
  })

  it('destructured from globalThis', () => {
    expect(failing('const { setInterval: every } = globalThis\nevery(load, 1000)')).toEqual(['interval'])
  })

  it('imported from the timers modules, renamed or as a namespace', () => {
    expect(failing("import { setInterval as every } from 'node:timers'\nevery(load, 1000)")).toEqual(['interval'])
    expect(failing("import timers from 'timers'\ntimers.setInterval(load, 1000)")).toEqual(['interval'])
    expect(failing("import { setInterval } from 'timers/promises'\nfor await (const _ of setInterval(1000)) await load()")).toEqual(['interval'])
  })

  it('passed as a value or an injected default', () => {
    expect(failing('function watch({ every = setInterval }) { return every(load, 1) }')).toEqual(['interval'])
    expect(failing('const later = setTimeout')).toEqual(['timeout-loop'])
  })

  it('hidden behind a helper in the same file: the helper and every call count', () => {
    const code = 'function every(fn, ms) { return setInterval(fn, ms) }\nevery(loadA, 5000)\nevery(loadB, 5000)'
    expect(failing(code)).toEqual(['interval', 'interval', 'interval'])
  })

  it('hidden behind a helper in another file, named or namespace import', () => {
    const r = scanFiles([
      { path: 'lib/poll.js', code: 'export function startPoll(fn) { return setInterval(fn, 30_000) }' },
      { path: 'app/a.js', code: "import { startPoll as go } from '../lib/poll.js'\ngo(load)" },
      { path: 'app/b.js', code: "import * as p from '../lib/poll'\np.startPoll(load)" }
    ])
    expect(r.get('app/a.js').map((f) => f.kind)).toEqual(['interval'])
    expect(r.get('app/b.js').map((f) => f.kind)).toEqual(['interval'])
  })

  it('setTimeout re-scheduling itself (named function, const arrow, callback calling back)', () => {
    expect(failing('function tick() { load(); setTimeout(tick, 1000) }')).toEqual(['timeout-loop'])
    expect(failing('const check = async () => { await load(); timer = setTimeout(check, 2000) }')).toEqual(['timeout-loop'])
    expect(failing('function tick() { setTimeout(() => { load(); tick() }, 1000) }')).toEqual(['timeout-loop'])
  })

  it('a sleep in a loop: inline, local helper, imported helper, injected default', () => {
    expect(failing('async function f() { while (true) { await load(); await new Promise((r) => setTimeout(r, 1000)) } }')).toEqual(['timeout-loop'])
    expect(failing('const sleep = (ms) => new Promise((r) => setTimeout(r, ms))\nasync function f() { for (;;) { await load(); await sleep(5) } }')).toEqual(['timeout-loop'])
    const r = scanFiles([
      { path: 'lib/sleep.js', code: 'export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))' },
      { path: 'app/c.js', code: "import { sleep } from '../lib/sleep.js'\nasync function f() { do { await load(); await sleep(1) } while (1) }" }
    ])
    expect(r.get('app/c.js').map((f) => f.kind)).toEqual(['timeout-loop'])
    expect(failing('async function f(sleep = (ms) => new Promise((r) => setTimeout(r, ms))) { for (;;) await sleep(1) }')).toEqual(['timeout-loop'])
  })

  it('a self-calling async poll with a sleep', () => {
    expect(failing('async function poll() { await load(); await new Promise((r) => setTimeout(r, 1000)); return poll() }')).toEqual(['timeout-loop'])
  })

  it('#554\'s TTL: a ttlFor hook and a TTL constant', () => {
    expect(failing("githubState.get('prs', repo, fetch, { ttlFor: pendingChecksTtl })")).toEqual(['ttl', 'ttl'])
    expect(failing('export const PENDING_CHECKS_TTL_MS = 90_000')).toEqual(['ttl'])
    expect(failing("const opts = { 'ttlFor': f }")).toEqual(['ttl'])
  })

  it('timers in .ts, .tsx and .jsx files', () => {
    expect(failing('const id: ReturnType<typeof setInterval> = setInterval((): void => load(), 1000 as number)', 'x.ts')).toEqual(['interval'])
    expect(failing('export function A<T,>(p: { x: T }) { useEffect(() => { const i = setInterval(load, 1e3); return () => clearInterval(i) }, []); return <div /> }', 'x.tsx')).toEqual(['interval'])
    expect(failing('export const A = () => { useEffect(() => { setInterval(load, 1e3) }, []); return <b>hi</b> }', 'x.jsx')).toEqual(['interval'])
  })

  it('an unparseable file fails closed', () => {
    expect(kinds('setInterval(load, 1000', 'x.js')).toEqual(['unparseable'])
  })
})

describe('the guard does not cry wolf', () => {
  it('comments, strings, template literals, regexes and JSX text mentioning setInterval', () => {
    const code = [
      '// setInterval(load, 1000)',
      '/* const t = setInterval(load, 1) */',
      "const a = 'setInterval(load, 1000)'",
      'const b = `setTimeout(tick, ${1})`',
      'const c = /setInterval/',
      'const d = { setInterval: 1, ttl: 0 }.setInterval',
      'export const E = () => <p>setInterval polls; ttlFor too</p>'
    ].join('\n')
    expect(failing(code, 'x.jsx')).toEqual(['ttl'])
  })

  it('one-shot setTimeouts: a debounce, an abort, a hide delay, an injected fake', () => {
    expect(failing('function emit(t) { clearTimeout(timers.get(t)); timers.set(t, setTimeout(() => fire(t), 300)) }')).toEqual([])
    expect(failing('const timer = setTimeout(() => controller.abort(), 5000)')).toEqual([])
    expect(failing('const hide = () => { timer.current = setTimeout(() => setOpen(false), 150) }')).toEqual([])
    expect(failing('function f({ setTimeout }) { return setTimeout(g, 1) }')).toEqual([])
    expect(failing('req.setTimeout(1000, () => req.destroy())\nclearInterval(id)')).toEqual([])
  })

  it('a one-shot sleep that is not in a loop', () => {
    expect(failing('const sleep = (ms) => new Promise((r) => setTimeout(r, ms))\nawait sleep(100)')).toEqual([])
  })
})

describe('the UI-clock rule is narrow (no network call inside), not a name match', () => {
  const clock = (inner, extra = '') => `function C() { const [now, setNow] = useState(Date.now()); const [, tick] = useState(0); ${extra}\nuseEffect(() => { const i = setInterval(${inner}, 1000); return () => clearInterval(i) }, []) }`

  it('repainting a clock with a useState setter is allowed', () => {
    expect(kinds(clock('() => setNow(Date.now())'))).toEqual(['ui-clock'])
    expect(kinds(clock('() => tick((n) => n + 1)'))).toEqual(['ui-clock'])
  })

  it('a setter plus any other call is not a clock', () => {
    expect(failing(clock('() => { setNow(Date.now()); load() }'))).toEqual(['interval'])
    expect(failing(clock('() => setNow(fetch("/x"))'))).toEqual(['interval'])
    expect(failing(clock('async () => setNow(await window.api.mr.list())'))).toEqual(['interval'])
  })

  it('a function named like a setter that is not from useState is not a clock', () => {
    expect(failing('const setNow = () => fetch("/x")\nsetInterval(() => setNow(Date.now()), 1000)')).toEqual(['interval'])
  })

  it('a callback passed by name is not a clock', () => {
    expect(failing(clock('repaint'))).toEqual(['interval'])
  })

  it('a clock whose state drives a useEffect (a disguised refetch) is not a clock', () => {
    expect(failing(clock('() => setNow(Date.now())', 'useEffect(() => { load() }, [now])'))).toEqual(['interval'])
  })
})

describe('the allowlist check', () => {
  const results = (findings) => new Map([['a.js', findings]])
  const f = (kind, line = 1) => ({ kind, line, why: kind })

  it('an allowlisted file gaining a second timer fails, naming the line', () => {
    const p = checkAllowlist(results([f('interval', 3), f('interval', 9)]), { 'a.js': { interval: [1, 'the one backstop poll'] } })
    expect(p.join('\n')).toMatch(/a\.js:9 interval/)
  })

  it('a stale entry (code lost a timer) fails, so a later timer can\'t slip in under it', () => {
    expect(checkAllowlist(results([]), { 'a.js': { ttl: [1, 'some cache lifetime'] } }).join('\n')).toMatch(/stale|Lower or remove/)
  })

  it('an entry without a real reason fails', () => {
    expect(checkAllowlist(results([f('interval')]), { 'a.js': { interval: [1, ''] } }).join('\n')).toMatch(/reason/)
    expect(checkAllowlist(results([f('interval')]), { 'a.js': { interval: 1 } }).join('\n')).toMatch(/reason/)
  })

  it('UI clocks need no entry; anything unlisted fails with the pointer to CONTEXT.md and gh_watch.js', () => {
    expect(checkAllowlist(results([f('ui-clock')]), {})).toEqual([])
    expect(checkAllowlist(results([f('unparseable')]), {})).toHaveLength(1)
    expect(GUIDANCE).toMatch(/Triggers over polling/)
    expect(GUIDANCE).toMatch(/gh_watch\.js/)
  })
})

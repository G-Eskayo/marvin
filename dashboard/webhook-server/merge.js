import { execFile, spawn } from 'child_process'
import { promisify } from 'util'
import { mkdtemp, rm, statfs, readdir, lstat } from 'fs/promises'
import { readdirSync, readFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { classifyFailure, summarizeGateFailure, withRetry, MergeFailure, refusal } from './failure.js'
import { recordFailure } from './failure_log.js'
import { assertUiEvidence } from './ui_evidence.js'
import { assertDecisions } from './decisions_gate.js'
import { fileURLToPath } from 'url'
import { sendFeedback } from './deny.js'
import { parseTicketRef } from '../electron/main/mr_review.js'
import { repoFromPrUrl, MARVIN_REPO } from '../electron/main/mr_repos.js'
import { recordStage } from './ticket_stages.js'
import { assertChecksGreen } from './ci_status.js'
import { checkOpenPrs } from './post_merge_rebase.js'
import { applyVersionBump } from './changelog.js'
import { createCountParser, gateExtension, machineLoad } from './merge_progress.js'
import { machineLabel } from '../src/lib/merge_progress.js'
import { holdTestSlot, TEST_SLOT_SCRIPT } from './test_slot.js'

const execFileAsync = promisify(execFile)
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_PATH = path.resolve(__dirname, '..', '..')
const REBUILD_SCRIPT = path.resolve(__dirname, '..', 'scripts', 'rebuild_and_install.sh')
const TICKET_PIPELINE_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'ticket_pipeline.py')
const MERGE_BACKUP_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'merge_backup.py')
const DISK_TRIGGERS_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'disk_triggers.py')
const MEMORY_GUARD_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'memory_guard.py')
const VENV_PYTHON = path.resolve(__dirname, '..', '..', 'venv', 'bin', 'python')
const PROFILE_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'project_profile.py')
const GENERATED_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'generated_paths.py')
const PURPOSE_METRICS_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'purpose_metrics.py')
const NODE_MODULES_SEED_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'node_modules_seed.py')

// #687: a gate copy gets node_modules as a copy-on-write clone of a cached install (lib/node_modules_seed.py), so the
// `npm install` below finds everything in place instead of writing ~0.8 GB. Best effort: a miss or an error just means
// npm installs as before, and the seed never runs through the gate's own exec (its clock and its command log).
export const nodeModulesCache = {
  seed: (dir) => execFileAsync(VENV_PYTHON, [NODE_MODULES_SEED_SCRIPT, 'seed', dir], { timeout: 120_000 }).catch(() => {}),
  store: (dir) => execFileAsync(VENV_PYTHON, [NODE_MODULES_SEED_SCRIPT, 'store', dir], { timeout: 120_000 }).catch(() => {})
}
// The per-command limit for commands run OUTSIDE the merge gate (gh reads, post-merge checks). Inside the gate the gate
// owns the clock (pipeline review 2026-10-21, F3): this 20-minute kill used to fire first, so #568's load-aware
// extension of the 40-minute gate limit could never apply, and a hung test was a silent 20-minute GATE_INFRA. Now a
// hung test fails in two minutes by name (pytest-timeout, pytest.ini), and the gate passes `signal` plus no limit here.
const DEFAULT_TEST_TIMEOUT_MS = 1200_000

// opts.onOutput(chunk), when given, sees the output as it arrives (marvin#568: live test counts, and the "still making
// progress" signal the gate's time limit reads). opts.signal (an AbortSignal), when given, kills the whole process
// group on abort: that is how the gate's own limit stops a run. Neither is passed on to spawn. timeoutMs that is not a
// positive finite number means no per-command limit (the caller's signal bounds it).
export async function execWithGroupTimeout(cmd, args, opts = {}, timeoutMs = DEFAULT_TEST_TIMEOUT_MS) {
  const { onOutput, signal, ...spawnOpts } = opts || {}
  if (signal?.aborted) throw Object.assign(new Error(`Cut off before it started (the merge gate's time limit ran out): ${cmd}`), { stdout: '', stderr: '' })
  const child = spawn(cmd, args, { ...spawnOpts, detached: true })
  let stdout = '', stderr = ''
  const seen = (d) => { if (onOutput) { try { onOutput(String(d)) } catch { /* a progress reader never breaks the run */ } } }
  if (child.stdout) child.stdout.on('data', (d) => { stdout += d; seen(d) })
  if (child.stderr) child.stderr.on('data', (d) => { stderr += d; seen(d) })
  const killGroup = () => { try { process.kill(-child.pid, 'SIGKILL') } catch { /* process may have already exited */ } }
  const promise = new Promise((resolve, reject) => {
    child.on('error', reject)
    child.on('close', (code) => {
      if (code === 0) resolve({ stdout, stderr })  // callers read it (gh pr list/view); resolving nothing broke them silently
      else reject(Object.assign(new Error(`Command failed with exit code ${code}`), { stdout, stderr, code }))
    })
  })
  let timer, onAbort
  const limits = []
  if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
    limits.push(new Promise((resolve, reject) => {
      timer = setTimeout(() => {
        killGroup()
        const mins = Math.max(1, Math.round(timeoutMs / 60000))
        reject(Object.assign(new Error(`Tests did not finish within ${mins} min and were killed, running: ${cmd}`), { stdout, stderr }))
      }, timeoutMs)
    }))
  }
  if (signal) {
    limits.push(new Promise((resolve, reject) => {
      onAbort = () => {
        killGroup()
        reject(Object.assign(new Error(`Cut off: the merge gate's time limit ran out, running: ${cmd}`), { stdout, stderr }))
      }
      signal.addEventListener('abort', onAbort, { once: true })
    }))
  }
  return Promise.race([promise, ...limits]).finally(() => {
    clearTimeout(timer)
    if (onAbort) signal.removeEventListener('abort', onAbort)
  })
}

// Inside the gate: every command gets the gate's abort signal and no per-command limit, so the gate's limit (with its
// one load-aware extension) is the only clock. Once the gate has been cut off, cleanup commands (worktree remove) run
// with the normal per-command limit instead of being killed on the spot. O(1) per command.
export function gateExec(exec, signal) {
  return (cmd, args, opts = {}, timeoutMs) => signal.aborted
    ? exec(cmd, args, opts, timeoutMs)
    : exec(cmd, args, { ...opts, signal }, timeoutMs ?? Infinity)
}

// The overlap rule (Gil 2026-10-09): a PR behind main is retested only when main changed a file the PR also changes
// since the two split. Different files cannot conflict in git; a cross-file break (one PR renames what another
// calls) is rare and is caught minutes later by main-health, which re-runs the suite on every main move and refuses
// merges while main is red. The same files are where conflicts and interactions concentrate, so those get the retest.
//
// Amended (Gil 2026-10-26): main also gets a say through its *rules*. A test or guard file main added or changed since
// the split may judge files the PR adds, which the PR's own earlier run never saw (#572 was tested on 10-21, main then
// gained test_instance_move.py, and its direct merge turned main red). So a PR is retested when main changed a rule.
export const RULE_FILE = /(^|\/)tests?\/|(^|\/)test_[^/]*\.py$|\.test\.[cm]?[jt]sx?$|(^|\/)conftest\.py$|(^|\/)pytest\.ini$|^config\/push-guard\/|^\.gitignore$/

// What main changed since the PR split: files the PR also changes, and rules (RULE_FILE). One fetch, one merge-base,
// two name-only diffs: O(files changed on either side).
export async function mainChanges(headRef, exec = execFileAsync, repoPath = REPO_PATH, base = 'main') {
  await exec('git', ['fetch', 'origin', base, headRef], { cwd: repoPath })
  const split = (await exec('git', ['merge-base', `origin/${base}`, `origin/${headRef}`], { cwd: repoPath })).stdout.trim()
  const changed = async (to) => new Set((await exec('git', ['diff', '--name-only', split, to], { cwd: repoPath })).stdout.split('\n').filter(Boolean))
  const [onBase, inPr] = await Promise.all([changed(`origin/${base}`), changed(`origin/${headRef}`)])
  return {
    shared: [...inPr].filter((f) => onBase.has(f)).sort(),
    rules: [...onBase].filter((f) => RULE_FILE.test(f)).sort()
  }
}

export async function sharedFiles(headRef, exec = execFileAsync, repoPath = REPO_PATH, base = 'main') {
  return (await mainChanges(headRef, exec, repoPath, base)).shared
}

// Would the PR still merge onto main? Answered by git merge-tree: no checkout, no tests, no push, seconds. Exit 1 is
// a conflict (the conflicted files follow the tree id); any other failure is an error, never reported as a conflict.
export async function conflictsWithBase(headRef, exec = execFileAsync, repoPath = REPO_PATH, base = 'main') {
  await exec('git', ['fetch', 'origin', base, headRef], { cwd: repoPath })
  try {
    await exec('git', ['merge-tree', '--write-tree', '--name-only', '--no-messages', `origin/${base}`, `origin/${headRef}`], { cwd: repoPath })
    return { conflict: false, files: [] }
  } catch (err) {
    if (err?.code !== 1) throw err
    const files = String(err.stdout || '').split('\n').slice(1).map((l) => l.trim()).filter(Boolean)
    return { conflict: true, files: [...new Set(files)].sort() }
  }
}

// ADR 0026: dispatch stays concurrent (no throttling), so two tickets can
// finish out of order -- whichever merges second may already be behind
// whatever the first merge just landed on main. `origin/main` being an
// ancestor of the branch means it's caught up; anything else (behind,
// diverged, or the ref/fetch itself failing) is treated as "needs the
// gate" -- safe to be conservative here since rebaseAndRetest() below is
// a no-op-if-already-clean rebase in the failure-adjacent cases.
export async function isBehindMain(headRef, exec = execFileAsync, repoPath = REPO_PATH, base = 'main') {
  await exec('git', ['fetch', 'origin', base, headRef], { cwd: repoPath })
  try {
    await exec('git', ['merge-base', '--is-ancestor', `origin/${base}`, `origin/${headRef}`], { cwd: repoPath })
    return false
  } catch {
    return true
  }
}

// How many dashboard test files vitest will run, for "120 of 183 files". 0 when unknown (the count then grows as it goes).
export function countTestFiles(dir) {
  try {
    return readdirSync(dir, { recursive: true }).filter((n) => !String(n).includes('node_modules') && /\.(test|spec)\.[cm]?[jt]sx?$/.test(String(n))).length
  } catch {
    return 0
  }
}

const noProgress = () => {}

// The Python suite runs in parallel (pytest-xdist): 327 s serial vs 47 s on the M4's 10 cores, same 2,685 tests,
// measured 2026-10-21. A machine without the plugin runs it serially and says so in the log, never fails on it.
// marvin#940: as many workers as fit in free memory now (lib/test_slot.py workers), not one per core: on 2026-10-30 the
// gate's `-n auto` workers were part of what filled the Mini's memory. An unreadable count is `-n auto`, as before.
// Two `python` calls per gate run (~0.2 s); not cached, so installing the plugin takes effect on the next run.
export async function pytestParallelArgs(python = VENV_PYTHON, run = execFileAsync, log = console.warn, slotScript = TEST_SLOT_SCRIPT) {
  try {
    await run(python, ['-c', 'import xdist'])
  } catch {
    try { log(`[merge-gate] pytest-xdist is not installed in ${python}: running the Python suite serially (slower). Fix: ${python} -m pip install pytest-xdist`) } catch { /* logging never breaks the gate */ }
    return []
  }
  try {
    const n = parseInt(String((await run(python, [slotScript, 'workers']))?.stdout || '').trim(), 10)
    if (n > 0) return ['-n', String(n)]
  } catch { /* unreadable: the old default */ }
  return ['-n', 'auto']
}

// The checks the gate runs: the repo's own required list (.github/required-checks.json, lib/required_checks.py,
// marvin#826), the one GitHub CI runs too, minus the CI-only ones. Read from the checkout under test, else the engine's
// own copy (a test's fake checkout). A list that exists but is broken throws: the gate must never run nothing.
export function gateChecks(cwd) {
  for (const dir of [cwd, REPO_PATH]) {
    let text
    try { text = readFileSync(path.join(dir, '.github', 'required-checks.json'), 'utf8') } catch { continue }
    let checks
    try { checks = JSON.parse(text).checks } catch (e) { throw new Error(`.github/required-checks.json is not valid JSON: ${e.message}`) }
    if (!Array.isArray(checks) || !checks.length) throw new Error('.github/required-checks.json lists no checks')
    return checks.filter((c) => (c.where || 'both') === 'both').map((c) => ({ cwd: '.', parser: 'exit-code', ...c }))
  }
  throw new Error('no .github/required-checks.json: the gate does not know which checks to run')
}

// What the progress line calls a check: the runners' own words where the stage UI already used them.
const CHECK_DETAIL = { pytest: 'Python', vitest: 'Dashboard' }

// base: the branch the PR is tested against. Each check then runs only what the PR's change can affect (marvin#826:
// run-check.sh skips a check none of whose paths changed; lib/affected_tests.py picks the Python tests). No base runs
// everything.
export { holdTestSlot }

export async function _defaultRunTests(cwd, exec, progress = noProgress, parallelArgs = pytestParallelArgs, cache = nodeModulesCache, base = null, holdSlot = holdTestSlot) {
  const checks = gateChecks(cwd)
  // `python` in a check is the venv's interpreter: its bin goes first on PATH.
  const PATH = [path.dirname(VENV_PYTHON), process.env.PATH].filter(Boolean).join(path.delimiter)
  const baseEnv = { ...process.env, PATH, MARVIN_MERGE_GATE: '1' }
  if (base) baseEnv.MARVIN_BASE = `origin/${base}`
  else delete baseEnv.MARVIN_BASE
  // Each output chunk is a heartbeat for the gate's time limit; the parsers turn the runners' own lines into counts.
  const watch = (runner, label, totalFiles = 0) => {
    const parse = createCountParser(runner, { totalFiles, onCount: (count) => progress('tests', 'running', { detail: label, count }) })
    return (chunk) => { progress('tests', 'output'); parse(chunk) }
  }
  // Installs first (marvin#568), so the stages read in order: Installing, then Tests.
  progress('installing', 'running')
  for (const c of checks.filter((c) => c.install === 'npm')) {
    // Nothing to install for a check this PR doesn't affect (a Python-only PR skips the dashboard's npm install).
    // Anything but a plain "false" installs: an unclear answer must not leave a check without its packages.
    const answer = await exec('bash', ['.github/run-check.sh', c.id, '--affected'], { cwd, env: baseEnv }).catch(() => ({ stdout: '' }))
    if (String(answer?.stdout || '').trim() === 'false') continue
    // Found live 2026-10-01 (PR #119's merge attempt): a `git worktree add` scratch checkout has no node_modules at
    // all, and `npx vitest run` hard-fails with a dependency-resolution wall that has nothing to do with the PR.
    // A scratch worktree is its own filesystem location, so nothing is symlinked in; (#687) a copy-on-write clone of
    // the cache is the safe way to start warm: the copy shares the cache's blocks but is its own files.
    const dir = path.join(cwd, c.cwd)
    await cache.seed(dir)
    await exec('npm', ['install'], { cwd: dir, onOutput: () => progress('installing', 'output') })
    await cache.store(dir)
  }
  progress('installing', 'done')
  const parallel = await parallelArgs()
  // marvin#940: one test run at a time on this machine, a merge first in line; the checks below see MARVIN_TEST_SLOT,
  // so their own check (conftest.py, vitest.config.js) passes straight through instead of waiting for us. The worker
  // count sized to free memory reaches both runners through MARVIN_TEST_WORKERS (lib/affected_tests.py, vitest.config.js).
  const slot = await holdSlot(['hold', '--merge', '--what', 'merge gate'])
  const slotEnv = { ...baseEnv, MARVIN_TEST_SLOT: 'merge gate' }
  if (/^\d+$/.test(parallel[1] || '')) slotEnv.MARVIN_TEST_WORKERS = parallel[1]
  else delete slotEnv.MARVIN_TEST_WORKERS
  try {
    for (const c of checks) {
      let label = CHECK_DETAIL[c.parser] || c.name
      // MARVIN_MERGE_GATE (in baseEnv): tests that read ANOTHER repo's data (the portfolio figures) stay out of a PR's
      // gate; they run in the main-branch health check instead (lib/main_health.py).
      if (c.parser === 'pytest') {
        if (!parallel.length) label = `${label} (serial: pytest-xdist missing)`
        progress('tests', 'running', { detail: label, logDetail: !parallel.length })
      } else {
        progress('tests', 'running', { detail: label, logDetail: true })
      }
      const total = c.parser === 'vitest' ? countTestFiles(path.join(cwd, c.cwd, 'test')) : 0
      const runner = c.parser === 'pytest' || c.parser === 'vitest' ? c.parser : null
      await exec('bash', ['.github/run-check.sh', c.id], { cwd, env: slotEnv, onOutput: runner ? watch(runner, CHECK_DETAIL[c.parser], total) : () => progress('tests', 'output') })
    }
  } finally {
    await slot.release()
  }
}

// Rebases headRef onto origin/main inside a throwaway scratch worktree --
// never the shared checkout, same collision-risk reasoning as
// sandbox_orchestration._create_worktree (an interactive session could be
// mid-edit on that checkout at the same moment) -- then re-runs the full
// test suite. Only pushes the rebased branch back if both steps succeed;
// a conflict or a test failure leaves the branch on origin untouched, and
// the scratch worktree is always removed regardless of outcome.
// What a failed test run printed. pytest and vitest write their failures to STDOUT, while execFile's message only
// says "Command failed", so the reason used to lose the failing test names (clarity of the comment, and the baseline
// check below, both need them).
function testOutputOf(err) {
  const out = String(err?.stdout || '').slice(-6000)
  const rest = String(err?.stderr || err?.message || err)
  return out ? `${out}\n${rest}` : rest
}

// marvin#866: the gate's temporary clones ($TMPDIR/mr-merge-gate-*, ~660 MB each, and the baseline's mr-baseline-*)
// outlived their merges: two were still there hours later on 2026-10-29, and the Mac mini's disk filled. Each one is
//   - named with this process's pid, and listed in `live` while its merge runs;
//   - removed in a finally (git's record, then the folder, with retries), on success, failure, a throw or the gate's
//     time limit;
//   - and, if the process died first (a restart mid-merge never runs the finally), removed by sweepGateClones when the
//     webhook next starts: anything older than GATE_CLONE_MAX_AGE_MS that is not in flight here and does not name
//     another live process.
// The in-flight record (merge_progress.js, ~/.claude/logs/merge-inflight.json) is per PR and holds no folder; it is
// emptied at startup by takeInterruptedMerges, so `live` (this process) plus the pid in the name (any other) is what
// says a clone is still in use. `root` is the seam tests point at a temp folder; never the real $TMPDIR there.
export const GATE_CLONE_PREFIXES = ['mr-merge-gate-', 'mr-baseline-']
export const GATE_CLONE_MAX_AGE_MS = 2 * 60 * 60_000
export const gateClones = { root: () => tmpdir(), live: new Set() }
const PID_IN_NAME = /^mr-(?:merge-gate|baseline)-(\d+)-/

async function makeGateClone(prefix) {
  const dir = await mkdtemp(path.join(gateClones.root(), `${prefix}${process.pid}-`))
  gateClones.live.add(dir)
  return dir
}

async function dropGateClone(dir, exec, repoPath) {
  try {
    await Promise.resolve().then(() => exec('git', ['worktree', 'remove', '--force', dir], { cwd: repoPath })).catch(() => {})
    try {
      await rm(dir, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 })
    } catch (e) {
      console.warn(`[merge] could not remove the gate's temporary copy ${dir}: ${e?.code || e?.message || e}; the next startup sweep will`)
    }
  } finally {
    gateClones.live.delete(dir)
  }
}

const pidAlive = (pid) => {
  try { process.kill(pid, 0); return true } catch (e) { return e?.code === 'EPERM' }
}

// O(entries in the temp folder) plus one rm per stale clone. Never throws; never follows a link.
export async function sweepGateClones({ root = gateClones.root(), live = gateClones.live, now = Date.now(), maxAgeMs = GATE_CLONE_MAX_AGE_MS, isAlive = pidAlive, repoPath = REPO_PATH, exec = execFileAsync, log = console.log } = {}) {
  const removed = [], kept = []
  let names = []
  try { names = await readdir(root) } catch { return { removed, kept } }
  for (const name of names) {
    if (!GATE_CLONE_PREFIXES.some((p) => name.startsWith(p))) continue
    const dir = path.join(root, name)
    let st
    try { st = await lstat(dir) } catch { continue }
    if (!st.isDirectory()) continue   // a link or a file with the name: not ours to delete
    const pid = Number((name.match(PID_IN_NAME) || [])[1]) || null
    let why = null
    if (live.has(dir)) why = 'its merge is running'
    else if (pid && pid !== process.pid && isAlive(pid)) why = `gate process ${pid} is still running`
    else if (now - st.mtimeMs < maxAgeMs) why = 'younger than the age limit'
    if (why) { kept.push({ name, reason: why }); continue }
    try {
      await rm(dir, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 })
      removed.push(name)
    } catch (e) {
      kept.push({ name, reason: `could not remove: ${e?.code || e?.message || e}` })
    }
  }
  if (removed.length && repoPath) await exec('git', ['worktree', 'prune'], { cwd: repoPath }).catch(() => {})
  if (removed.length) log(`[merge] startup sweep removed ${removed.length} leftover gate cop${removed.length === 1 ? 'y' : 'ies'}: ${removed.join(', ')}`)
  return { removed, kept }
}

// Which of these failing tests ALSO fail on a clean checkout of the base branch? If they do, the PR did not break them:
// the base was already red. Only pytest ids (`path::name`) can be re-run individually; anything else returns null
// ("cannot tell"), and the caller behaves as before. Used by the webhook; tests inject their own.
export async function baselineFailsOnMain(names, exec = execFileAsync, repoPath = REPO_PATH, base = 'main') {
  if (!names.length || names.some((n) => !n.includes('::'))) return null
  const dir = await makeGateClone('mr-baseline-')
  try {
    await exec('git', ['fetch', 'origin', base], { cwd: repoPath })
    await exec('git', ['worktree', 'add', '--detach', dir, `origin/${base}`], { cwd: repoPath })
    try {
      await exec(VENV_PYTHON, ['-m', 'pytest', '-q', '-p', 'no:cacheprovider', ...names], { cwd: dir, env: { ...process.env, MARVIN_MERGE_GATE: '1' } })
      return []
    } catch (e) {
      const out = String(e?.stdout || '')
      return out ? names.filter((n) => out.includes(`FAILED ${n}`)) : null
    }
  } catch {
    return null
  } finally {
    await dropGateClone(dir, exec, repoPath)
  }
}

// The gate copies the repo (about 650 MB for marvin) and runs the suite in it, and the baseline check may copy main as
// well. Below this, tests fail in ways that read as the PR's fault (a write cut short), so the gate refuses first.
export const MIN_GATE_FREE_BYTES = 5 * 1024 ** 3

export async function freeDiskBytes(dir = tmpdir()) {
  const s = await statfs(dir)
  return s.bavail * s.bsize
}

// First aid for a nearly full disk (2026-10-28: macOS's aerial wallpaper refilled the Mac mini between daily sweeps and
// two Approves were refused). The registered step `disk-clear-rebuildable` in lib/purpose_metrics.py FIRST_AID runs the
// cleanup sweep's own rebuildable trims (lib/cleanup_sweep.py clear_rebuildable: aerial videos keep-newest, disk_trim's
// allowlisted caches): no deletion rule of its own. Never throws; a failed run is a failed step.
export const DISK_FIRST_AID_STEP = 'disk-clear-rebuildable'
const DISK_FIRST_AID_TIMEOUT_MS = 10 * 60_000

export async function runDiskFirstAid(exec = execFileAsync) {
  try {
    const { stdout } = await exec(VENV_PYTHON, [PURPOSE_METRICS_SCRIPT, 'first-aid', DISK_FIRST_AID_STEP, '--local'], { timeout: DISK_FIRST_AID_TIMEOUT_MS })
    const last = String(stdout || '').trim().split('\n').pop() || ''
    const r = JSON.parse(last)
    if (!r || typeof r !== 'object' || Array.isArray(r)) throw new Error('no answer')
    return { ok: !!r.ok, changed: !!r.changed, detail: String(r.detail || '').slice(0, 300) }
  } catch (e) {
    const why = String(e?.stderr || e?.message || e).trim().split('\n').pop() || 'no answer'
    return { ok: false, changed: false, detail: `first aid could not run: ${why.slice(0, 200)}` }
  }
}

export async function rebaseAndRetest(headRef, exec = execFileAsync, repoPath = REPO_PATH, runTests = _defaultRunTests, base = 'main', resolveConflicts = null, sleep = null, progress = noProgress, freeBytes = freeDiskBytes, firstAid = null) {
  let free = await freeBytes(tmpdir()).catch(() => null) // unreadable: carry on, as before this check
  const gb = (n) => `${(n / 1024 ** 3).toFixed(1)} GB`
  let aidNote = ''
  if (free !== null && free < MIN_GATE_FREE_BYTES && firstAid) {
    // Once per approve: one call here, no retry loop. Only then refuse.
    progress('rebasing', 'running', { detail: `disk nearly full (${gb(free)} free): clearing rebuildable files first`, logDetail: true })
    let aid
    try { aid = await firstAid() } catch (e) { aid = { ok: false, detail: `first aid failed: ${String(e?.message || e).slice(0, 200)}` } }
    if (!aid || typeof aid !== 'object') aid = { ok: false, detail: 'first aid gave no answer' }
    const detail = String(aid.detail || (aid.ok ? 'nothing to clear' : 'first aid failed')).replace(/\s+/g, ' ').slice(0, 300)
    const before = free
    free = await freeBytes(tmpdir()).catch(() => null)
    progress('rebasing', 'running', { detail: `first aid: ${detail}; ${free === null ? 'free space unreadable' : `${gb(free)} free now`} (was ${gb(before)})`, logDetail: true })
    aidNote = `\n\nFirst aid ran first: ${detail}; ${free === null ? 'free space unreadable' : `${gb(free)} free`} after.`
  }
  if (free !== null && free < MIN_GATE_FREE_BYTES) {
    // Worded so summarizeGateFailure files it as GATE_INFRA (the machine, not the PR, and nothing is sent back) and
    // infraCause can name the disk and both numbers.
    return { ok: false, reason: `Disk check before rebasing onto ${base}:\n\nNo space left on device for the check: ${gb(free)} free, the gate needs ${gb(MIN_GATE_FREE_BYTES)}. Free up space on this Mac, then approve again.${aidNote}` }
  }
  const scratchDir = await makeGateClone('mr-merge-gate-')
  try {
    progress('rebasing', 'running', { detail: `onto ${base}` })   // inside the try: a throw here must not leak the clone
    await exec('git', ['fetch', 'origin', base, headRef], { cwd: repoPath })
    await exec('git', ['worktree', 'add', '--detach', scratchDir, `origin/${headRef}`], { cwd: repoPath })

    try {
      await exec('git', ['rebase', `origin/${base}`], { cwd: scratchDir })
    } catch (err) {
      // A project can declare generated files (profile "generated"); a rebase that conflicts ONLY in those
      // is finished by the resolver (main's copy, regenerated). Real code conflicts still end here.
      const resolved = resolveConflicts ? await resolveConflicts(scratchDir).catch((e) => ({ ok: false, reason: String(e.message || e) })) : null
      if (!resolved?.ok) {
        const why = resolved?.reason ? `\n\nGenerated-file resolution: ${resolved.reason}` : ''
        return { ok: false, reason: `Rebase onto main failed:\n\n${String(err.stderr || err.message || err)}${why}` }
      }
    }

    progress('rebasing', 'done')
    try {
      await runTests(scratchDir, exec, progress, undefined, undefined, base)
    } catch (err) {
      return { ok: false, reason: `Tests failed after rebasing onto main:\n\n${testOutputOf(err)}` }
    }
    progress('tests', 'done')

    // The retest above may have taken many minutes; a GitHub blip on the push must not discard it.
    await withRetry(() => exec('git', ['push', '--force-with-lease', 'origin', `HEAD:${headRef}`], { cwd: scratchDir }), {
      classify: (e) => classifyFailure({ stage: 'gate', error: e }),
      ...(sleep ? { sleep } : {})
    })
    return { ok: true }
  } finally {
    await dropGateClone(scratchDir, exec, repoPath)
  }
}

// Fetches what the gate needs to know for one PR and decides whether it
// applies. Fails open (gate: false) on any error -- a hiccup in this
// metadata fetch is a reason to fall back to today's direct-merge
// behavior, not a reason to block an otherwise-fine merge.
// Behind main is not enough on its own (the overlap rule, sharedFiles above): only a PR whose files main also changed
// is rebased and retested. When the overlap can't be worked out, it is retested, to be safe.
export async function defaultShouldGateMerge(prUrl, exec, ctx = null) {
  let headRefName = null, body = ''
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'headRefName,body'])
    ;({ headRefName, body } = JSON.parse(stdout))
    body = body || ''
    const behind = ctx ? await isBehindMain(headRefName, exec, ctx.clone, ctx.base) : await isBehindMain(headRefName, exec)
    if (!behind) return { gate: false, behind: false, shared: [], headRefName, body }
    let changes = null
    try {
      changes = ctx ? await mainChanges(headRefName, exec, ctx.clone, ctx.base) : await mainChanges(headRefName, exec)
    } catch { /* unknown overlap: retest */ }
    const gate = changes === null || changes.shared.length > 0 || changes.rules.length > 0
    return { gate, behind: true, shared: changes?.shared || [], rules: changes?.rules || [], headRefName, body }
  } catch {
    return { gate: false, behind: false, shared: [], headRefName, body }
  }
}
const _defaultShouldGateMerge = defaultShouldGateMerge

// What the gate needs for a project other than marvin, from that project's execution profile
// (lib/project_profile.py). Refuses -- as coded failures, not exceptions the HTTP layer would call
// a server error -- a project that never opted in, one with no clone on this machine, and a machine
// lacking a tool the project's required checks need (that last one is about the machine, so the
// ticket is NOT sent back for rework).
export async function defaultGateContext(repo, exec = execFileAsync) {
  const { stdout } = await exec(VENV_PYTHON, [PROFILE_SCRIPT, 'gate-info', repo])
  const info = JSON.parse(stdout)
  const name = repo.split('/').pop()
  if (info.profile === false || !info.merge_from_dashboard) {
    throw new MergeFailure(refusal('NO_MERGE_PROFILE', 'request', `${name} is not set up for merging from the dashboard`,
      `Review and merge it on GitHub, or set "merge_from_dashboard": true in config/projects/${name}.json.`))
  }
  if (!info.clone) {
    throw new MergeFailure(refusal('NO_MERGE_PROFILE', 'request', `there is no clone of ${name} on the machine running the webhook`,
      `Clone ${repo} on that machine (or add its path to clone_hints in the profile).`))
  }
  if (info.missing_here.length) {
    throw new MergeFailure(refusal('ENV_MISSING', 'request', `this machine lacks ${info.missing_here.join(', ')}, which ${name}'s required checks need`,
      'Run the webhook on a machine that has the toolchain, or install it here. The PR was not sent back for rework.'))
  }
  return {
    repo,
    clone: info.clone,
    base: info.base_branch,
    // The same measuring code the pipeline uses, so "passes the gate" means what "passes verification" means.
    runTests: async (cwd, run, progress = noProgress) => {
      progress('tests', 'running', { detail: name })
      // MARVIN_BASE: the project's checks run only what the PR affects, as its CI does (marvin#826).
      await run(VENV_PYTHON, [PROFILE_SCRIPT, 'verify', repo, cwd], { env: { ...process.env, MARVIN_BASE: `origin/${info.base_branch}` }, onOutput: () => progress('tests', 'output') })
    },
    resolveConflicts: generatedResolver(repo, exec),
    // The project's own UI paths, added to ui_evidence.js's defaults (marvin #374).
    uiPaths: Array.isArray(info.ui_paths) ? info.ui_paths : []
  }
}

// Finishes a conflicted rebase when every conflict is a generated file, or main already has the PR's change to that
// file (parallel PRs that each added the same thing). Real conflicts still fail. marvin uses it too (#225), with the
// default rules in lib/generated_paths.py (it has no project profile).
function generatedResolver(repo, exec) {
  return async (cwd) => {
    try {
      const { stdout } = await exec(VENV_PYTHON, [GENERATED_SCRIPT, 'resolve-rebase', repo, cwd])
      return JSON.parse(stdout)
    } catch (e) {
      let parsed = null
      try { parsed = JSON.parse(e.stdout) } catch { /* not JSON */ }
      return parsed || { ok: false, reason: String(e.message || e) }
    }
  }
}

// A merge queue of one per repo. Two merges (or a merge gate and a pipeline build) running at once is what
// produced "Base branch was modified", database-locked builds and rebases against a main that moved mid-gate.
// Merging one PR changes what every other PR must be tested against, so they go one at a time, in the order
// asked. A failure never blocks the ones behind it. Different repos do not wait for each other.
const repoQueues = new Map()
const queueDepth = new Map() // jobs queued or running per repo, for "Queued: 1 merge ahead" (marvin#568)
function inRepoQueue(key, fn) {
  const prev = repoQueues.get(key) || Promise.resolve()
  queueDepth.set(key, (queueDepth.get(key) || 0) + 1)
  const run = prev.then(fn, fn)
  const tail = run.catch(() => {})
  repoQueues.set(key, tail)
  tail.then(() => {
    const left = (queueDepth.get(key) || 1) - 1
    if (left > 0) queueDepth.set(key, left)
    else queueDepth.delete(key)
    if (repoQueues.get(key) === tail) repoQueues.delete(key)
  })
  return run
}

// How many jobs (merges, post-merge checks) a new merge of this PR would wait behind.
export function mergesAhead(prUrl) {
  return queueDepth.get(repoFromPrUrl(prUrl) || '(unknown)') || 0
}

export function mergePr(prUrl, ...rest) {
  return inRepoQueue(repoFromPrUrl(prUrl) || '(unknown)', () => mergePrUnqueued(prUrl, ...rest))
}

function prNumberOf(prUrl) {
  const m = String(prUrl).match(/\/pull\/(\d+)/)
  return m ? Number(m[1]) : 0
}

// Separated from the HTTP plumbing in index.js so this -- the part that
// actually matters -- is unit-testable without spinning up a real server
// or hitting real GitHub.
// `gh pr merge` merges into whatever branch the PR TARGETS. A PR aimed at a side branch (a stacked PR whose
// parent was never merged to main) therefore reports "merged" while its work never reaches the base branch
// (finance-os #8 did exactly that on 2026-10-05). Refuse it, say where it points, and leave the PR alone.
// A metadata hiccup does not block: the merge itself would then fail loudly on its own.
export async function assertTargetsBase(prUrl, exec, expectedBase) {
  let base
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'baseRefName'])
    base = JSON.parse(stdout).baseRefName
  } catch {
    return
  }
  if (base && base !== expectedBase) {
    throw new MergeFailure(refusal('WRONG_BASE', 'request',
      `this PR targets "${base}", not ${expectedBase}: merging it would not put the work on ${expectedBase}`,
      `Merge or retarget its parent first, or change its base to ${expectedBase} on GitHub. The PR was not sent back for rework.`))
  }
}

// A ticket that was sent back for rework carries `needs-reengagement` while its PR stays open. The review screen
// shows that as "sent back: waiting for rework", but nothing stopped the PR being merged anyway (marvin #129), which
// would land work that was just rejected. Refuse it here, so no caller can bypass the screen. The label is on the
// ticket, in the PR's OWN repository (ticket numbers are per repo). A lookup hiccup never blocks: the merge itself
// would fail loudly on its own, same policy as assertTargetsBase.
export async function assertNotSentBack(prUrl, exec) {
  let sentBack = false
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'body'])
    const ticket = parseTicketRef(JSON.parse(stdout).body || '')
    const repo = repoFromPrUrl(prUrl)
    if (ticket && repo) {
      const { stdout: issueOut } = await exec('gh', ['issue', 'view', ticket, '--repo', repo, '--json', 'labels'])
      sentBack = (JSON.parse(issueOut).labels || []).some((l) => l.name === 'needs-reengagement')
    }
  } catch {
    return
  }
  if (sentBack) {
    throw new MergeFailure(refusal('SENT_BACK', 'request',
      'this PR\'s ticket was sent back for rework, so the work in this PR was rejected and a reworked version is on its way',
      'Wait for the reworked PR. If the rework is already in and the "needs-reengagement" label is just stale, remove that label from the ticket and approve again. The PR was not changed.'))
  }
}

// Only a human's Approve reaches mergePr (dashboard and phone), so that click is the "ready" decision for a draft.
// Before this, a draft ran the whole rebase-and-retest gate and then failed at merge with "Pull Request is still
// a draft", reported as UNKNOWN (clarity-captions #77/#78, 2026-10-09). Mark it ready first, say so on the PR, and
// refuse plainly if GitHub won't. A lookup hiccup never blocks, same policy as assertTargetsBase.
export async function readyIfDraft(prUrl, exec) {
  let isDraft = false
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'isDraft'])
    isDraft = JSON.parse(stdout).isDraft === true
  } catch {
    return false
  }
  if (!isDraft) return false
  try {
    await exec('gh', ['pr', 'ready', prUrl])
  } catch (error) {
    const reason = String(error?.stderr || error?.message || error).split('\n')[0]
    throw new MergeFailure(refusal('PR_DRAFT', 'request',
      `this PR is a draft and GitHub would not mark it ready: ${reason}`,
      'Mark it "Ready for review" on GitHub, then approve again. The PR was not changed or sent back.'))
  }
  try {
    await exec('gh', ['pr', 'comment', prUrl, '--body', 'Marked ready for review because the owner pressed Approve on this draft.'])
  } catch {}
  return true
}

// What GitHub says about the PR right now, waiting out "UNKNOWN" (it recomputes a PR's mergeability after every
// push, including the merge gate's own rebase push, and answers UNKNOWN or a stale "not mergeable" meanwhile).
export async function mergeableNow(prUrl, exec, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), tries = 6, delayMs = 5000) {
  let state = 'UNKNOWN'
  for (let i = 0; i < tries; i++) {
    try {
      const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'mergeable'])
      state = JSON.parse(stdout).mergeable || 'UNKNOWN'
    } catch {
      state = 'UNKNOWN'
    }
    if (state !== 'UNKNOWN') return state
    await sleep(delayMs)
  }
  return state
}

// The longest a gate (rebase + the project's whole check, including an app build) may take. Nothing used to bound it: a
// test run that blocked reading an iCloud-managed folder under launchd sat forever, and three approvals of marvin #147
// vanished with no result (2026-10-06). Past the limit the gate is abandoned and reported as the machine's problem,
// not the PR's.
export const GATE_TIMEOUT_MS = 40 * 60_000

// The limit is decided when it runs out (marvin#568): `decide()` may extend it once, with a stated reason (a busy
// machine whose tests are still printing), or say why it is cut off. Two fixed deadlines, never a loop.
const CUT = Symbol('cut')
function deadline(promise, ms) {
  let timer
  const cut = new Promise((resolve) => { timer = setTimeout(() => resolve(CUT), ms) })
  return Promise.race([promise, cut]).finally(() => clearTimeout(timer))
}
const cutOff = (ms, note) => ({ ok: false, reason: `Tests failed after rebasing onto main:\n\nThe check did not finish within ${Math.max(1, Math.round(ms / 60000))} min and was cut off.${note ? ` ${note}.` : ''}` })

// onCut runs when the limit finally runs out, before the result is returned: the gate aborts its commands there, so a
// cut-off run is killed, not left running behind the next merge.
export async function withGateTimeout(promise, ms, decide = () => ({ extendMs: 0 }), onExtend = () => {}, onCut = () => {}) {
  const cut = (result) => { try { onCut() } catch { /* stopping must not break the report */ } return result }
  const first = await deadline(promise, ms)
  if (first !== CUT) return first
  let d = { extendMs: 0 }
  try { d = decide() || d } catch { /* no extension */ }
  if (!(d.extendMs > 0)) return cut(cutOff(ms, d.note))
  try { onExtend(d.reason) } catch { /* reporting must not break the gate */ }
  const second = await deadline(promise, d.extendMs)
  if (second !== CUT) return second
  let after = { extendMs: 0 }
  try { after = decide() || after } catch { /* as above */ }
  return cut(cutOff(ms + d.extendMs, `It was extended once already (${d.reason})${after.note ? `; at the end ${after.note}` : ''}`))
}

async function mergePrUnqueued(
  prUrl,
  exec = execWithGroupTimeout,
  rebuild = triggerRebuildIfDashboardChanged,
  redispatch = triggerAfterMerge,
  shouldGateMerge = _defaultShouldGateMerge,
  rebaseAndRetestFn = rebaseAndRetest,
  reengage = sendFeedback,
  recordStageFn = recordStage,
  deps = {}
) {
  const { sleep, recordFailureFn = recordFailure, gateContext = defaultGateContext, baselineFails = null, gateTimeoutMs = GATE_TIMEOUT_MS, rebaseOpen = checkOpenPrs, uiEvidence = assertUiEvidence, decisions = assertDecisions,
    progress: report = noProgress, loadNow = () => machineLoad(), now = Date.now, diskFirstAid = null, memoryCheck = null } = deps
  if (typeof prUrl !== 'string' || !prUrl.startsWith('https://github.com/')) {
    throw new MergeFailure(classifyFailure({ stage: 'request', error: new Error(`Not a GitHub PR URL: ${prUrl}`) }))
  }
  // marvin#568: each stage is reported as it starts and ends (index.js turns that into pushed events and log lines).
  // Output from the tests is a heartbeat: the time limit reads it to tell "slow" from "hung".
  let lastOutputAt = null
  const progress = (stage, state, extra) => {
    if (state === 'output' || extra?.count) lastOutputAt = now()
    try { report(stage, state, extra) } catch { /* a progress reader never breaks the merge */ }
  }
  progress('fetching', 'running')

  // marvin's own PRs use the built-in gate. Any other project needs its profile to say it may be
  // merged from here -- enforced here, not just on the screen.
  const repo = repoFromPrUrl(prUrl)
  const ctx = repo && repo !== MARVIN_REPO ? await gateContext(repo, exec) : null

  await assertTargetsBase(prUrl, exec, ctx ? ctx.base : 'main')
  await assertNotSentBack(prUrl, exec)
  const draftWasMarkedReady = await readyIfDraft(prUrl, exec)
  // A UI change merges only with images the owner has seen (marvin #374). Before any gate work: refusing is cheap.
  await uiEvidence(prUrl, exec, ctx ? ctx.uiPaths : [])
  // A PR that asks the owner to choose merges only once he has answered, in its Decisions section (2026-10-09).
  await decisions(prUrl, exec)

  const { gate, behind = false, headRefName, body, shared = [], rules = [] } = ctx ? await shouldGateMerge(prUrl, exec, ctx) : await shouldGateMerge(prUrl, exec)
  const ticketNumber = parseTicketRef(body)
  // Every call below is a no-op (not an error) when ticketNumber is null
  // -- a manually-authored PR with no linked ticket has nothing to record
  // a timeline against, same "fails open" spirit as _defaultShouldGateMerge.
  // Another project's tickets are recorded under that project (#7 there is not #7 in marvin).
  const stage = (name, status, detail) => {
    if (ticketNumber === null) return
    if (ctx) recordStageFn(ticketNumber, name, status, detail, { repo })
    else recordStageFn(ticketNumber, name, status, detail)
  }

  // Record the draft → ready step for pipeline visibility (#217).
  if (draftWasMarkedReady) {
    stage('merging', 'passed', 'marked ready for review (owner pressed Approve on this draft)')
  }

  // The repo's own CI (GitHub checks), when it has any: failing means the code is wrong and the PR goes back
  // with the check names; still running means wait. Before the gate, so no machine time is spent on a red PR.
  try {
    await assertChecksGreen(prUrl, exec)
  } catch (e) {
    if (e instanceof MergeFailure && e.payload.code === 'CI_FAILED' && ticketNumber !== null) {
      stage('gate', 'failed', `CI_FAILED: ${e.payload.message}`)
      recordFailureFn({ ticket: ticketNumber, code: 'CI_FAILED', message: e.payload.message, project: repo, prUrl, stage: 'gate' })
      const comment = `**CI: failing checks**\n\n${e.payload.message}\n\nFix what these report, then the ticket will be rebuilt.`
      await reengage({ prUrl, ticketNumber, reasons: ['Regression/quality'], comment }, exec)
      return { merged: false, reengaged: true, code: 'CI_FAILED', stage: 'gate', action: 'reengage', reason: comment }
    }
    throw e
  }

  progress('fetching', 'done', { gated: !!gate })
  if (!gate) {
    const why = behind ? `${ctx ? ctx.base : 'main'} changed none of this PR's files` : `already up to date with ${ctx ? ctx.base : 'main'}`
    for (const s of ['rebasing', 'installing', 'tests']) progress(s, 'skipped', { detail: `no retest needed: ${why}` })
  }
  if (!gate && behind) {
    stage('gate', 'passed', `no retest needed: behind ${ctx ? ctx.base : 'main'}, but ${ctx ? ctx.base : 'main'} changed none of this PR's files, so it merges directly (main-health re-runs the suite after the merge)`)
  }
  if (gate) {
    const baseName = ctx ? ctx.base : 'main'
    const reason = shared.length ? `${baseName} changed files this PR also changes`
      : rules.length ? `${baseName} has new or changed tests or guard rules since this PR was tested (${rules.slice(0, 3).join(', ')})`
      : `${baseName} moved on and the overlap could not be read`
    // marvin#845: the rebase + retest is heavy work; it waits while memory pressure is at warn or critical. The check
    // queues this Approve to run again when macOS reports pressure back at normal. Nothing running is stopped. A check
    // that can't run never blocks a merge (as an unreadable disk).
    let held = null
    if (memoryCheck) { try { held = await memoryCheck(prUrl) } catch { held = null } }
    if (held && held.ok === false) {
      stage('gate', 'failed', `MEMORY_PRESSURE: ${held.message}`)
      throw new MergeFailure(refusal('MEMORY_PRESSURE', 'gate', held.message,
        held.queued ? 'Nothing to do: it starts by itself when memory pressure drops.' : 'Approve it again when memory pressure drops.',
        held.queued ? 'retry' : 'escalate'))
    }
    stage('gate', 'started', `rebasing onto ${baseName} + retesting (${reason})`)
    // One clock (pipeline review 2026-10-21, F3): the gate's limit, extended at most once under load. Its commands run
    // with no per-command limit of their own and are killed through this signal when it finally runs out.
    const gateAbort = new AbortController()
    const run = gateExec(exec, gateAbort.signal)
    const result = await withGateTimeout(
      Promise.resolve(ctx
        ? rebaseAndRetestFn(headRefName, run, ctx.clone, ctx.runTests, ctx.base, ctx.resolveConflicts, sleep ?? null, progress, undefined, diskFirstAid)
        : rebaseAndRetestFn(headRefName, run, REPO_PATH, _defaultRunTests, 'main', generatedResolver(MARVIN_REPO, run), sleep ?? null, progress, undefined, diskFirstAid)),
      gateTimeoutMs,
      () => gateExtension({ baseMs: gateTimeoutMs, load: loadNow(), lastOutputAt, now: now() }),
      (reason) => progress('tests', 'running', { detail: reason, logDetail: true }),
      () => gateAbort.abort())
    if (!result.ok) {
      // Structured, concise feedback (code header, failing test names, capped tail)
      // instead of a raw output wall: this comment is what the ticket's executor reads
      // to decide how to fix its work, so it has to be parseable and to the point.
      let where = null
      try { where = loadNow()?.id ? machineLabel(loadNow().id) : null } catch { /* unknown machine: "This Mac" */ }
      const summary = summarizeGateFailure(result.reason, { where })
      if (summary.code === 'GATE_INFRA') {
        // The machine failed, not the PR: leave the ticket and PR alone so it can simply be approved again.
        const timedOut = /did not finish within \d+ min/.test(summary.comment)
        // marvin#568: say what the machine was doing when the limit ran out (busy, or idle so the tests hung).
        const loadNote = (String(result.reason).match(/cut off\. (.+?)\.?\s*$/s) || [])[1]
        // 2026-10-28: the cause the gate knows (a full disk, a locked build database, ...) is the message, so the
        // dashboard, MR Review, the stage strip and the webhook log all say it instead of a generic line.
        const message = timedOut
          ? `the check on this PR did not finish in time and was cut off${loadNote ? ` (${loadNote})` : ''}. That points at the machine or its setup, not at the PR's code`
          : `${summary.cause || "The build machine or the project's test setup failed while checking this PR"}. That is the machine, not the PR's code`
        stage('gate', 'failed', `GATE_INFRA: ${timedOut ? 'the check did not finish in time' : summary.cause || 'the build machine or test setup failed, not the code'}`)
        throw new MergeFailure(refusal('GATE_INFRA', 'gate', message,
          // A named cause says it all; only an unnamed one keeps the raw output for a person to read.
          `${summary.next || 'Approve it again.'} The PR was not sent back for rework.${summary.cause ? '' : ` What failed: ${summary.comment.slice(0, 300)}`}`))
      }
      if (summary.code === 'GATE_TESTS_FAILED' && summary.failingTests.length && baselineFails) {
        // Did the PR break these, or was the base branch already red? Only a test that passes on the base is the PR's fault.
        const onBase = await baselineFails(summary.failingTests).catch(() => null)
        if (Array.isArray(onBase) && summary.failingTests.every((n) => onBase.includes(n))) {
          stage('gate', 'failed', `MAIN_RED: ${summary.failingTests.length} failing test(s) also fail on ${ctx ? ctx.base : 'main'}`)
          throw new MergeFailure(refusal('MAIN_RED', 'gate',
            `${ctx ? ctx.base : 'main'} itself fails ${summary.failingTests.length === 1 ? 'this test' : 'these tests'}, so this PR cannot be judged yet: ${summary.failingTests.slice(0, 3).join(', ')}`,
            `Fix ${ctx ? ctx.base : 'main'} first, then approve again. The PR was not sent back, because it did not cause this.`))
        }
      }
      stage('gate', 'failed', `${summary.code}: ${summary.failingTests.length ? summary.failingTests.length + ' failing test(s)' : 'see comment'}`)
      recordFailureFn({ ticket: ticketNumber ?? prNumberOf(prUrl), code: summary.code, message: summary.failingTests[0] || 'merge gate failed', project: repo, prUrl, stage: 'gate' })
      // ADR 0025's existing re-engagement path, not a new failure state:
      // structured comment on both PR and ticket, claim released, tagged
      // needs-reengagement. The PR itself stays open for a human or a
      // future re-engagement pass -- this isn't a "drop" outcome.
      await reengage(
        { prUrl, ticketNumber, reasons: ['Regression/quality'], comment: summary.comment },
        exec
      )
      return { merged: false, reengaged: true, code: summary.code, stage: 'gate', action: 'reengage',
               failingTests: summary.failingTests, reason: summary.comment }
    }
    stage('gate', 'passed', 'rebased and retested clean')
  }

  // No code review here: it runs in the build loop before the PR opens (sandbox_orchestration.execute_ticket).
  // Approve only checks the PR merges cleanly: CI, conflicts, retest after a rebase.

  stage('merging', 'started', '')
  progress('merging', 'running')
  let mergeError = null
  // "Not mergeable" straight after our own rebase push is usually GitHub still recomputing the PR, not a conflict
  // (finance-os, clarity #66: a good PR was denied and its ticket wrongly sent back). So when merging says that, ask
  // GitHub whether it really conflicts; only CONFLICTING is a conflict, anything else gets another try.
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      // Transient failures (network, rate limit) are retried with backoff right here, so
      // a blip never reaches the human or the pipeline as a failure.
      await withRetry(() => exec('gh', ['pr', 'merge', prUrl, '--merge']), {
        classify: (e) => classifyFailure({ stage: 'merging', error: e }),
        ...(sleep ? { sleep } : {})
      })
      mergeError = null
      break
    } catch (error) {
      mergeError = error
      if (classifyFailure({ stage: 'merging', error }).code !== 'NOT_MERGEABLE') break
      if ((await mergeableNow(prUrl, exec, sleep)) === 'CONFLICTING') break
    }
  }
  if (mergeError) {
    const error = mergeError
    if (classifyFailure({ stage: 'merging', error }).code === 'NOT_MERGEABLE' && (await mergeableNow(prUrl, exec, sleep)) !== 'CONFLICTING') {
      stage('merging', 'failed', 'MERGE_REFUSED: GitHub refuses it but does not report a conflict')
      throw new MergeFailure(refusal('MERGE_REFUSED', 'merging', 'GitHub refused the merge but does not report a conflict on this PR',
        'Approve again in a minute. The ticket was not sent back, because nothing says the work is wrong.'))
    }
    const failure = classifyFailure({ stage: 'merging', error })
    failure.attempts = error.attempts ?? 1
    stage('merging', 'failed', `${failure.code}: ${failure.message}`)
    recordFailureFn({ ticket: ticketNumber ?? prNumberOf(prUrl), code: failure.code, message: failure.message, project: repo, prUrl, stage: 'merging' })
    if (failure.action === 'reengage' && ticketNumber !== null) {
      // The PR's own work needs changing (e.g. conflicts main moved past): hand it back to
      // the ticket with the detail, the same path the gate uses, instead of dead-ending.
      await reengage(
        { prUrl, ticketNumber, reasons: ['Regression/quality'],
          comment: `**Merge: ${failure.code}**\n\n${failure.remediation}\n\nEvidence:\n\`\`\`\n${failure.evidence}\n\`\`\`` },
        exec
      )
      return { merged: false, reengaged: true, code: failure.code, stage: 'merging', action: 'reengage', reason: failure.message }
    }
    throw new MergeFailure(failure)
  }
  stage('merging', 'passed', '')
  progress('merging', 'done')
  progress('after', 'running')
  if (!ctx && ticketNumber !== null) {
    stage('versioning', 'started', '')
    try {
      await applyVersionBump({ ticketNumber, prUrl }, exec, REPO_PATH)
      stage('versioning', 'passed', '')
    } catch (e) {
      stage('versioning', 'failed', `VERSION_BUMP_FAILED: ${String(e?.message || e).slice(0, 300)}`)
      recordFailureFn({ ticket: ticketNumber, code: 'VERSION_BUMP_FAILED', message: String(e?.message || e), project: repo, prUrl, stage: 'versioning' })
    }
  }
  if (!ctx) {
    // marvin-only: the dashboard app is rebuilt when a merged PR touched dashboard/.
    stage('rebuilding', 'started', 'triggered if the PR touched dashboard/')
    await rebuild(prUrl, exec)
  }
  // #225 (overlap rule, 2026-10-09): move stacked PRs onto the base and conflict-check the other open PRs (queued
  // behind this merge, so the response does not wait; no tests, no pushes), then run the pipeline scan.
  const integrateRepo = repo || MARVIN_REPO
  const check = (head) => conflictsWithBase(head, exec, ctx ? ctx.clone : REPO_PATH, ctx ? ctx.base : 'main')
  inRepoQueue(integrateRepo, () => rebaseOpen({ repo: integrateRepo, mergedPrUrl: prUrl, base: ctx ? ctx.base : 'main', exec, check }))
    .catch((e) => console.error(`[post-merge] ${integrateRepo}: after ${prUrl}: ${String(e?.message || e).slice(0, 300)}`))
    .then(() => redispatch())
  progress('after', 'done')
  stage('done', 'passed', `merged: ${prUrl}`)
  return { merged: true, reengaged: false, reason: null }
}

// A merge landing code doesn't mean anyone's actually running it -- the
// dashboard is a native app in /Applications, not a web page that
// refreshes itself. If the merged PR touched dashboard/, rebuild and
// reinstall it so the change is actually visible, not just in git.
// Fire-and-forget by design: the approve click shouldn't block on a full
// npm build, and a rebuild failure shouldn't undo an already-successful
// merge -- errors here are swallowed on purpose (spawn is detached), same
// reasoning as check_and_trigger_merge.py's independent trigger step.
export async function triggerRebuildIfDashboardChanged(prUrl, exec = execFileAsync, spawnFn = spawn) {
  let touched
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'files', '--jq', '.files[].path'])
    touched = stdout.split('\n').filter(Boolean)
  } catch {
    return
  }
  if (!touched.some((p) => p.startsWith('dashboard/'))) return

  spawnFn(REBUILD_SCRIPT, [], { detached: true, stdio: 'ignore' }).unref()
}

// A merge means whichever machine implemented this ticket has been free
// since its PR was raised, potentially a while before this review
// happened -- rather than wait for the next hourly ticket_pipeline cron
// tick, check for more unclaimed work right now. Fire-and-forget, same
// reasoning as the rebuild trigger above: ticket_pipeline.py already
// no-ops safely if nothing's unclaimed or no machine is free, so nothing
// here needs to check first, and a failed scan shouldn't undo the merge
// that already succeeded. Unconditional (every merge, not just
// dashboard-touching ones) -- this isn't about what the merged PR
// touched, it's about a machine having freed up.
export function triggerTicketPipeline(spawnFn = spawn) {
  spawnFn(VENV_PYTHON, [TICKET_PIPELINE_SCRIPT], { detached: true, stdio: 'ignore' }).unref()
}

// marvin#765: a merge is also when the space its work used can come back. Every Mac removes the worktrees of merged
// PRs (wherever they are, ~/Developer/<repo>-<n> included) and their Xcode build products; anything with uncommitted
// work, a process inside, or commits the PR lacks is kept (lib/disk_triggers.py). Fire-and-forget, like the scan.
// marvin#845: ask lib/memory_guard.py before the gate's heavy work. Refused (exit 3), this same Approve is queued as a
// POST to this Mac's webhook, to run when macOS reports memory pressure back at normal. Any other failure: go ahead.
// marvin#940: the queued POST says `by: 'memory-queue'`, so its end tells the dashboards (they show it waiting).
export async function memoryGuardCheck(prUrl, port, exec = execFileAsync) {
  const what = `PR #${prNumberOf(prUrl) ?? '?'}`
  const approve = ['/usr/bin/curl', '-sS', '-X', 'POST', '-H', 'Content-Type: application/json',
    '--data', JSON.stringify({ pr_url: prUrl, by: 'memory-queue' }), `http://127.0.0.1:${port}/approve`]
  try {
    await exec(VENV_PYTHON, [MEMORY_GUARD_SCRIPT, 'check', '--what', what, '--key', `merge:${prUrl}`, '--', ...approve], { timeout: 30_000 })
    return { ok: true }
  } catch (e) {
    if (e?.code !== 3) return { ok: true }
    const message = String(e.stderr || '').trim().split('\n').pop() || `This Mac's memory is under pressure, so ${what} waits.`
    let queued = true
    try { queued = JSON.parse(String(e.stdout || '').trim().split('\n').pop()).queued !== false } catch { /* default: queued */ }
    return { ok: false, queued, message }
  }
}

// marvin#940: a merge of this PR is starting (a second Approve, a retry from a dashboard): its copy queued for memory,
// if any, is dropped, so the queue never runs it again. True when one was there. Never fails a merge.
export async function forgetQueuedMerge(prUrl, exec = execFileAsync) {
  try {
    const { stdout } = await exec(VENV_PYTHON, [MEMORY_GUARD_SCRIPT, 'forget', '--key', `merge:${prUrl}`], { timeout: 30_000 })
    return JSON.parse(String(stdout || '').trim().split('\n').pop()).forgotten === true
  } catch {
    return false
  }
}

// marvin#940 part 4: is this machine fit to merge in the Mini's place (GET /merge-ready)? lib/merge_backup.py answers
// { ready, why, machine, os }; a check that fails is "not fit", so a dashboard never sends a merge on a guess.
export async function readMergeReady(repo, exec = execFileAsync) {
  try {
    const { stdout } = await exec(VENV_PYTHON, [MERGE_BACKUP_SCRIPT, 'ready', '--repo', String(repo || '')], { timeout: 30_000 })
    return JSON.parse(String(stdout || '').trim().split('\n').pop())
  } catch (e) {
    return { ready: false, why: [`it couldn't check itself (${String(e?.message || e).slice(0, 100)})`], machine: null, os: null }
  }
}

// marvin#845: a merge ending is a trigger to start the next item queued for memory (a no-op when nothing waits).
export function kickMemoryGuard(spawnFn = spawn) {
  try { spawnFn(VENV_PYTHON, [MEMORY_GUARD_SCRIPT, 'kick'], { detached: true, stdio: 'ignore' }).unref() } catch { /* never breaks a merge */ }
}

// marvin#940 (merges first): a merge is marked on this machine (lib/test_slot.py merges.lock) from the Approve to its
// end, so new helpers wait while it runs (memory_guard.py) and other test runs let it go first. The mark is let go
// before the kick, so the drain the kick starts already sees the merge over. A mark that can't be taken never stops
// the merge; the merge's own error comes through unchanged.
export async function withMergeMark(merge, { hold = holdTestSlot, kick = kickMemoryGuard } = {}) {
  let mark = null
  try { mark = await hold(['hold-merge']) } catch { /* unmarked: the merge goes ahead */ }
  try {
    return await merge()
  } finally {
    try { await mark?.release() } catch { /* the holder ends with this process anyway */ }
    kick()
  }
}

export function triggerDiskCleanup(spawnFn = spawn) {
  spawnFn(VENV_PYTHON, [DISK_TRIGGERS_SCRIPT, 'after-merge'], { detached: true, stdio: 'ignore' }).unref()
}

// What a merge starts once the other open PRs are checked: the pipeline scan and the disk cleanup. Each is started on
// its own, so one failing to spawn never stops the other.
export function triggerAfterMerge(spawnFn = spawn) {
  for (const start of [triggerTicketPipeline, triggerDiskCleanup]) {
    try { start(spawnFn) } catch (e) { console.error(`[post-merge] ${start.name}: ${String(e?.message || e).slice(0, 200)}`) }
  }
}

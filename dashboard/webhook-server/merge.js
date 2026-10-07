import { execFile, spawn } from 'child_process'
import { promisify } from 'util'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'
import { classifyFailure, summarizeGateFailure, withRetry, MergeFailure, refusal } from './failure.js'
import { recordFailure } from './failure_log.js'
import { fileURLToPath } from 'url'
import { sendFeedback } from './deny.js'
import { parseTicketRef } from '../electron/main/mr_review.js'
import { repoFromPrUrl, MARVIN_REPO } from '../electron/main/mr_repos.js'
import { recordStage } from './ticket_stages.js'
import { assertChecksGreen } from './ci_status.js'

const execFileAsync = promisify(execFile)
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_PATH = path.resolve(__dirname, '..', '..')
const REBUILD_SCRIPT = path.resolve(__dirname, '..', 'scripts', 'rebuild_and_install.sh')
const TICKET_PIPELINE_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'ticket_pipeline.py')
const VENV_PYTHON = path.resolve(__dirname, '..', '..', 'venv', 'bin', 'python')
const PROFILE_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'project_profile.py')
const GENERATED_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'generated_paths.py')

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

export async function _defaultRunTests(cwd, exec) {
  // MARVIN_MERGE_GATE: tests that read ANOTHER repo's data (the portfolio figures) stay out of a PR's gate; they run in the
  // main-branch health check instead (lib/main_health.py).
  await exec(VENV_PYTHON, ['-m', 'pytest', '-q'], { cwd, env: { ...process.env, MARVIN_MERGE_GATE: '1' } })
  // Found live 2026-10-01 (PR #119's merge attempt): a `git worktree add`
  // scratch checkout has no dashboard/node_modules at all -- `npx vitest
  // run` hard-fails with a dependency-resolution error wall that has
  // nothing to do with the PR's own code, and the webhook relayed that
  // wall verbatim as the re-engagement reason. npm install is slower than
  // reusing the real checkout's node_modules, but a scratch worktree is a
  // separate filesystem location so nothing can be shared/symlinked in
  // safely without risking the exact collision this isolation exists to
  // avoid.
  const dashboardDir = path.join(cwd, 'dashboard')
  await exec('npm', ['install'], { cwd: dashboardDir })
  await exec('npx', ['vitest', 'run'], { cwd: dashboardDir })
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

// Which of these failing tests ALSO fail on a clean checkout of the base branch? If they do, the PR did not break them:
// the base was already red. Only pytest ids (`path::name`) can be re-run individually; anything else returns null
// ("cannot tell"), and the caller behaves as before. Used by the webhook; tests inject their own.
export async function baselineFailsOnMain(names, exec = execFileAsync, repoPath = REPO_PATH, base = 'main') {
  if (!names.length || names.some((n) => !n.includes('::'))) return null
  const dir = await mkdtemp(path.join(tmpdir(), 'mr-baseline-'))
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
    await exec('git', ['worktree', 'remove', '--force', dir], { cwd: repoPath }).catch(() => {})
    await rm(dir, { recursive: true, force: true }).catch(() => {})
  }
}

export async function rebaseAndRetest(headRef, exec = execFileAsync, repoPath = REPO_PATH, runTests = _defaultRunTests, base = 'main', resolveConflicts = null) {
  const scratchDir = await mkdtemp(path.join(tmpdir(), 'mr-merge-gate-'))
  try {
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

    try {
      await runTests(scratchDir, exec)
    } catch (err) {
      return { ok: false, reason: `Tests failed after rebasing onto main:\n\n${testOutputOf(err)}` }
    }

    await exec('git', ['push', '--force-with-lease', 'origin', `HEAD:${headRef}`], { cwd: scratchDir })
    return { ok: true }
  } finally {
    await exec('git', ['worktree', 'remove', '--force', scratchDir], { cwd: repoPath }).catch(() => {})
    await rm(scratchDir, { recursive: true, force: true }).catch(() => {})
  }
}

// Fetches what the gate needs to know for one PR and decides whether it
// applies. Fails open (gate: false) on any error -- a hiccup in this
// metadata fetch is a reason to fall back to today's direct-merge
// behavior, not a reason to block an otherwise-fine merge.
async function _defaultShouldGateMerge(prUrl, exec, ctx = null) {
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'headRefName,body'])
    const { headRefName, body } = JSON.parse(stdout)
    const behind = ctx ? await isBehindMain(headRefName, exec, ctx.clone, ctx.base) : await isBehindMain(headRefName, exec)
    return { gate: behind, headRefName, body: body || '' }
  } catch {
    return { gate: false, headRefName: null, body: '' }
  }
}

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
    runTests: async (cwd, run) => {
      await run(VENV_PYTHON, [PROFILE_SCRIPT, 'verify', repo, cwd])
    },
    // Finishes a conflicted rebase when every conflict is a generated file, or main already has the PR's
    // change to that file (parallel PRs that each added the same thing). Real conflicts still fail.
    resolveConflicts: async (cwd) => {
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
}

// A merge queue of one per repo. Two merges (or a merge gate and a pipeline build) running at once is what
// produced "Base branch was modified", database-locked builds and rebases against a main that moved mid-gate.
// Merging one PR changes what every other PR must be tested against, so they go one at a time, in the order
// asked. A failure never blocks the ones behind it. Different repos do not wait for each other.
const repoQueues = new Map()
function inRepoQueue(key, fn) {
  const prev = repoQueues.get(key) || Promise.resolve()
  const run = prev.then(fn, fn)
  const tail = run.catch(() => {})
  repoQueues.set(key, tail)
  tail.then(() => { if (repoQueues.get(key) === tail) repoQueues.delete(key) })
  return run
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

function withGateTimeout(promise, ms) {
  let timer
  const cut = new Promise((resolve) => {
    timer = setTimeout(() => resolve({ ok: false, reason: `Tests failed after rebasing onto main:\n\nThe check did not finish within ${Math.max(1, Math.round(ms / 60000))} min and was cut off.` }), ms)
  })
  return Promise.race([promise, cut]).finally(() => clearTimeout(timer))
}

async function mergePrUnqueued(
  prUrl,
  exec = execFileAsync,
  rebuild = triggerRebuildIfDashboardChanged,
  redispatch = triggerTicketPipeline,
  shouldGateMerge = _defaultShouldGateMerge,
  rebaseAndRetestFn = rebaseAndRetest,
  reengage = sendFeedback,
  recordStageFn = recordStage,
  deps = {}
) {
  const { sleep, recordFailureFn = recordFailure, gateContext = defaultGateContext, baselineFails = null, gateTimeoutMs = GATE_TIMEOUT_MS } = deps
  if (typeof prUrl !== 'string' || !prUrl.startsWith('https://github.com/')) {
    throw new MergeFailure(classifyFailure({ stage: 'request', error: new Error(`Not a GitHub PR URL: ${prUrl}`) }))
  }

  // marvin's own PRs use the built-in gate. Any other project needs its profile to say it may be
  // merged from here -- enforced here, not just on the screen.
  const repo = repoFromPrUrl(prUrl)
  const ctx = repo && repo !== MARVIN_REPO ? await gateContext(repo, exec) : null

  await assertTargetsBase(prUrl, exec, ctx ? ctx.base : 'main')
  await assertNotSentBack(prUrl, exec)

  const { gate, headRefName, body } = ctx ? await shouldGateMerge(prUrl, exec, ctx) : await shouldGateMerge(prUrl, exec)
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

  // The repo's own CI (GitHub checks), when it has any: failing means the code is wrong and the PR goes back
  // with the check names; still running means wait. Before the gate, so no machine time is spent on a red PR.
  try {
    await assertChecksGreen(prUrl, exec)
  } catch (e) {
    if (e instanceof MergeFailure && e.payload.code === 'CI_FAILED' && ticketNumber !== null) {
      stage('gate', 'failed', `CI_FAILED: ${e.payload.message}`)
      recordFailureFn({ ticket: ticketNumber, code: 'CI_FAILED', message: e.payload.message })
      const comment = `**CI: failing checks**\n\n${e.payload.message}\n\nFix what these report, then the ticket will be rebuilt.`
      await reengage({ prUrl, ticketNumber, reasons: ['Regression/quality'], comment }, exec)
      return { merged: false, reengaged: true, code: 'CI_FAILED', stage: 'gate', action: 'reengage', reason: comment }
    }
    throw e
  }

  if (gate) {
    stage('gate', 'started', `rebasing onto ${ctx ? ctx.base : 'main'} + retesting`)
    const result = await withGateTimeout(
      Promise.resolve(ctx
        ? rebaseAndRetestFn(headRefName, exec, ctx.clone, ctx.runTests, ctx.base, ctx.resolveConflicts)
        : rebaseAndRetestFn(headRefName, exec)),
      gateTimeoutMs)
    if (!result.ok) {
      // Structured, concise feedback (code header, failing test names, capped tail)
      // instead of a raw output wall: this comment is what the ticket's executor reads
      // to decide how to fix its work, so it has to be parseable and to the point.
      const summary = summarizeGateFailure(result.reason)
      if (summary.code === 'GATE_INFRA') {
        // The machine failed, not the PR: leave the ticket and PR alone so it can simply be approved again.
        stage('gate', 'failed', 'GATE_INFRA: the build machine or test setup failed, not the code')
        const timedOut = /did not finish within \d+ min/.test(summary.comment)
        throw new MergeFailure(refusal('GATE_INFRA', 'gate', timedOut
          ? 'the check on this PR did not finish in time and was cut off. That points at the machine or its setup, not at the PR\'s code'
          : 'the build machine or the project\'s test setup failed while checking this PR, not the PR\'s code',
          `Approve it again. The PR was not sent back for rework. What failed: ${summary.comment.slice(0, 300)}`))
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
      recordFailureFn({ ticket: ticketNumber ?? prNumberOf(prUrl), code: summary.code, message: summary.failingTests[0] || 'merge gate failed' })
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

  stage('merging', 'started', '')
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
    recordFailureFn({ ticket: ticketNumber ?? prNumberOf(prUrl), code: failure.code, message: failure.message })
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
  if (!ctx) {
    // marvin-only: the dashboard app is rebuilt when a merged PR touched dashboard/.
    stage('rebuilding', 'started', 'triggered if the PR touched dashboard/')
    await rebuild(prUrl, exec)
  }
  redispatch()
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

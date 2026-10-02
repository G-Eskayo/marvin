import { execFile, spawn } from 'child_process'
import { promisify } from 'util'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'
import { classifyFailure, summarizeGateFailure, withRetry, MergeFailure } from './failure.js'
import { recordFailure } from './failure_log.js'
import { fileURLToPath } from 'url'
import { sendFeedback } from './deny.js'
import { parseTicketRef } from '../electron/main/mr_review.js'
import { recordStage } from './ticket_stages.js'

const execFileAsync = promisify(execFile)
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_PATH = path.resolve(__dirname, '..', '..')
const REBUILD_SCRIPT = path.resolve(__dirname, '..', 'scripts', 'rebuild_and_install.sh')
const TICKET_PIPELINE_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'ticket_pipeline.py')
const VENV_PYTHON = path.resolve(__dirname, '..', '..', 'venv', 'bin', 'python')

// ADR 0026: dispatch stays concurrent (no throttling), so two tickets can
// finish out of order -- whichever merges second may already be behind
// whatever the first merge just landed on main. `origin/main` being an
// ancestor of the branch means it's caught up; anything else (behind,
// diverged, or the ref/fetch itself failing) is treated as "needs the
// gate" -- safe to be conservative here since rebaseAndRetest() below is
// a no-op-if-already-clean rebase in the failure-adjacent cases.
export async function isBehindMain(headRef, exec = execFileAsync, repoPath = REPO_PATH) {
  await exec('git', ['fetch', 'origin', 'main', headRef], { cwd: repoPath })
  try {
    await exec('git', ['merge-base', '--is-ancestor', 'origin/main', `origin/${headRef}`], { cwd: repoPath })
    return false
  } catch {
    return true
  }
}

export async function _defaultRunTests(cwd, exec) {
  await exec(VENV_PYTHON, ['-m', 'pytest', '-q'], { cwd })
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
export async function rebaseAndRetest(headRef, exec = execFileAsync, repoPath = REPO_PATH, runTests = _defaultRunTests) {
  const scratchDir = await mkdtemp(path.join(tmpdir(), 'mr-merge-gate-'))
  try {
    await exec('git', ['fetch', 'origin', 'main', headRef], { cwd: repoPath })
    await exec('git', ['worktree', 'add', '--detach', scratchDir, `origin/${headRef}`], { cwd: repoPath })

    try {
      await exec('git', ['rebase', 'origin/main'], { cwd: scratchDir })
    } catch (err) {
      return { ok: false, reason: `Rebase onto main failed:\n\n${String(err.stderr || err.message || err)}` }
    }

    try {
      await runTests(scratchDir, exec)
    } catch (err) {
      return { ok: false, reason: `Tests failed after rebasing onto main:\n\n${String(err.stderr || err.message || err)}` }
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
async function _defaultShouldGateMerge(prUrl, exec) {
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'headRefName,body'])
    const { headRefName, body } = JSON.parse(stdout)
    const behind = await isBehindMain(headRefName, exec)
    return { gate: behind, headRefName, body: body || '' }
  } catch {
    return { gate: false, headRefName: null, body: '' }
  }
}

function prNumberOf(prUrl) {
  const m = String(prUrl).match(/\/pull\/(\d+)/)
  return m ? Number(m[1]) : 0
}

// Separated from the HTTP plumbing in index.js so this -- the part that
// actually matters -- is unit-testable without spinning up a real server
// or hitting real GitHub.
export async function mergePr(
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
  const { sleep, recordFailureFn = recordFailure } = deps
  if (typeof prUrl !== 'string' || !prUrl.startsWith('https://github.com/')) {
    throw new MergeFailure(classifyFailure({ stage: 'request', error: new Error(`Not a GitHub PR URL: ${prUrl}`) }))
  }

  const { gate, headRefName, body } = await shouldGateMerge(prUrl, exec)
  const ticketNumber = parseTicketRef(body)
  // Every call below is a no-op (not an error) when ticketNumber is null
  // -- a manually-authored PR with no linked ticket has nothing to record
  // a timeline against, same "fails open" spirit as _defaultShouldGateMerge.
  const stage = (name, status, detail) => {
    if (ticketNumber !== null) recordStageFn(ticketNumber, name, status, detail)
  }

  if (gate) {
    stage('gate', 'started', 'rebasing onto main + retesting')
    const result = await rebaseAndRetestFn(headRefName, exec)
    if (!result.ok) {
      // Structured, concise feedback (code header, failing test names, capped tail)
      // instead of a raw output wall: this comment is what the ticket's executor reads
      // to decide how to fix its work, so it has to be parseable and to the point.
      const summary = summarizeGateFailure(result.reason)
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
  try {
    // Transient failures (network, rate limit) are retried with backoff right here, so
    // a blip never reaches the human or the pipeline as a failure.
    await withRetry(() => exec('gh', ['pr', 'merge', prUrl, '--merge']), {
      classify: (e) => classifyFailure({ stage: 'merging', error: e }),
      ...(sleep ? { sleep } : {})
    })
  } catch (error) {
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
  stage('rebuilding', 'started', 'triggered if the PR touched dashboard/')
  await rebuild(prUrl, exec)
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

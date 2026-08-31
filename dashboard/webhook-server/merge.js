import { execFile, spawn } from 'child_process'
import { promisify } from 'util'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'
import { fileURLToPath } from 'url'
import { sendFeedback } from './deny.js'
import { parseTicketRef } from '../electron/main/mr_review.js'

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

async function _defaultRunTests(cwd, exec) {
  await exec(VENV_PYTHON, ['-m', 'pytest', '-q'], { cwd })
  await exec('npx', ['vitest', 'run'], { cwd: path.join(cwd, 'dashboard') })
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
  reengage = sendFeedback
) {
  if (typeof prUrl !== 'string' || !prUrl.startsWith('https://github.com/')) {
    throw new Error(`Not a GitHub PR URL: ${prUrl}`)
  }

  const { gate, headRefName, body } = await shouldGateMerge(prUrl, exec)
  if (gate) {
    const result = await rebaseAndRetestFn(headRefName, exec)
    if (!result.ok) {
      // ADR 0025's existing re-engagement path, not a new failure state:
      // structured comment on both PR and ticket, claim released, tagged
      // needs-reengagement. The PR itself stays open for a human or a
      // future re-engagement pass -- this isn't a "drop" outcome.
      await reengage(
        { prUrl, ticketNumber: parseTicketRef(body), reasons: ['Regression/quality'], comment: result.reason },
        exec
      )
      return { merged: false, reengaged: true, reason: result.reason }
    }
  }

  await exec('gh', ['pr', 'merge', prUrl, '--merge'])
  await rebuild(prUrl, exec)
  redispatch()
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

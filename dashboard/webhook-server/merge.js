import { execFile, spawn } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import { fileURLToPath } from 'url'

const execFileAsync = promisify(execFile)
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REBUILD_SCRIPT = path.resolve(__dirname, '..', 'scripts', 'rebuild_and_install.sh')
const TICKET_PIPELINE_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'ticket_pipeline.py')
const VENV_PYTHON = path.resolve(__dirname, '..', '..', 'venv', 'bin', 'python')

// Separated from the HTTP plumbing in index.js so this -- the part that
// actually matters -- is unit-testable without spinning up a real server
// or hitting real GitHub.
export async function mergePr(
  prUrl,
  exec = execFileAsync,
  rebuild = triggerRebuildIfDashboardChanged,
  redispatch = triggerTicketPipeline
) {
  if (typeof prUrl !== 'string' || !prUrl.startsWith('https://github.com/')) {
    throw new Error(`Not a GitHub PR URL: ${prUrl}`)
  }
  await exec('gh', ['pr', 'merge', prUrl, '--merge'])
  await rebuild(prUrl, exec)
  redispatch()
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

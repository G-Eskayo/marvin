import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// Parallel-dispatch settings (ADR 0052). lib/dispatch_concurrency.py is the one validator and the one writer of
// config/dispatch.json; this only asks it. Saving also kicks the code sync so the other machine sees the change
// within a minute instead of the next half hour.
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CLI = path.join(homedir(), '.agents', 'lib', 'dispatch_concurrency.py')

function defaultRun(args) {
  return new Promise((resolve, reject) =>
    execFile(PY, [CLI, ...args], { timeout: 20000 }, (err, stdout, stderr) =>
      err ? reject(new Error((stderr || err.message).trim())) : resolve(stdout)
    )
  )
}

function defaultKick() {
  return new Promise((resolve) =>
    execFile('launchctl', ['kickstart', `gui/${process.getuid()}/com.marvin.code-sync-push`], () => resolve())
  )
}

export async function getConcurrency({ run = defaultRun } = {}) {
  return JSON.parse(await run(['get']))
}

// Invalid limits are refused with the reason and nothing is saved. A failed sync kick never fails the save.
export async function setConcurrency(settings, { run = defaultRun, kick = defaultKick } = {}) {
  const saved = JSON.parse(await run(['set', JSON.stringify(settings)]))
  try { await kick() } catch { /* the hourly sync still carries it */ }
  return saved
}

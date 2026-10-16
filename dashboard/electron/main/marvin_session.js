import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// The MARVIN button (marvin#228): opens a ready Interactive MARVIN session in WezTerm on this Mac. The work lives in
// lib/marvin_session.py (worktree, environment, WezTerm); this only asks it and reports what it said. Desktop only:
// the phone's backend has no route to it.
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const SESSION_CLI = path.join(homedir(), '.agents', 'lib', 'marvin_session.py')

export function sessionArgs({ ticket, repo, proposal } = {}) {
  const args = [SESSION_CLI, 'open']
  if (proposal != null) {
    // Ask MARVIN about a proposal (#102): a session at home with the proposal loaded as its first message.
    if (ticket != null && ticket !== '') throw new Error('open a ticket or a proposal, not both')
    if (typeof proposal !== 'string' || !/^[a-z0-9][a-z0-9-]{0,79}$/.test(proposal)) throw new Error('not a proposal id')
    return [...args, '--proposal', proposal]
  }
  const n = ticket == null || ticket === '' ? null : Number(String(ticket).replace(/^#/, ''))
  if (n !== null) {
    if (!Number.isInteger(n) || n <= 0) throw new Error(`"${ticket}" isn't a ticket number`)
    args.push('--ticket', String(n))
  }
  if (repo) args.push('--repo', repo)
  return args
}

export function openMarvinSession(request, { run = execFile } = {}) {
  let args
  try {
    args = sessionArgs(request)
  } catch (err) {
    return Promise.resolve({ ok: false, error: err.message })
  }
  return new Promise((resolve) => {
    run(PY, args, { timeout: 120000 }, (err, stdout, stderr) => {
      try {
        resolve(JSON.parse(String(stdout).trim().split('\n').pop()))
      } catch {
        resolve({ ok: false, error: (stderr || err?.message || 'the session launcher gave no answer').slice(0, 300) })
      }
    })
  })
}

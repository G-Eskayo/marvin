import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// MR Review → Proposals (#102, ADR 0068). The store and every rule about it live in lib/proposals.py; this only asks
// it and reports what it said, so there is one parser for the format, not two.
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CLI = path.join(homedir(), '.agents', 'lib', 'proposals.py')
export const PROPOSAL_ID = /^[a-z0-9][a-z0-9-]{0,79}$/
const ACTIONS = new Set(['ticket', 'snooze', 'dismiss', 'until'])

export function proposalArgs(cmd, id, action, args) {
  if (cmd === 'list') return [CLI, 'list']
  if (typeof id !== 'string' || !PROPOSAL_ID.test(id)) throw new Error('not a proposal id')
  if (!ACTIONS.has(action)) throw new Error(`unknown action: ${String(action).slice(0, 30)}`)
  const payload = args && typeof args === 'object' && !Array.isArray(args) ? args : {}
  return [CLI, 'act', id, action, '--json', JSON.stringify(payload)]
}

function call(run, args) {
  return new Promise((resolve) => {
    run(PY, args, { timeout: 90000, maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
      let parsed = null
      try {
        parsed = JSON.parse(String(stdout).trim().split('\n').pop())
      } catch {
        // fall through to the error below
      }
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return resolve(parsed)
      resolve({ ok: false, error: (stderr || err?.message || 'the proposals store gave no answer').slice(0, 300) })
    })
  })
}

export function createProposals({ run = execFile } = {}) {
  return {
    async list() {
      const out = await call(run, proposalArgs('list'))
      if (out.ok === false) return out
      if (!Array.isArray(out.proposals)) return { ok: false, error: 'the proposals store answered without a list' }
      return { ok: true, proposals: out.proposals, problems: Array.isArray(out.problems) ? out.problems : [] }
    },
    async act(id, action, args) {
      let argv
      try {
        argv = proposalArgs('act', id, action, args)
      } catch (err) {
        return { ok: false, error: err.message }
      }
      return call(run, argv)
    }
  }
}

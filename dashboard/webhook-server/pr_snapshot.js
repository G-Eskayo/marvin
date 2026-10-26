// One read for the approve preflight (pipeline review P5, 2026-10-21). merge.js's checks each read the PR they guard:
// base branch, body (sent back), draft, files + body (UI evidence), body (Decisions), head + body (retest needed?) and
// the checks: seven `gh pr view` calls one after another, 5.5 s for PR #569, each paying the GitHub gate's start-up.
// This wraps the exec the merge is given: the first of those reads fetches every field at once, and the rest are
// answered from that snapshot, each with exactly the fields it asked for. The checks and merge.js are unchanged.
//
// It is one snapshot of one moment, the same exposure the seven reads had (they spanned ~5 s). It ends at the first
// call that writes (gh pr ready, a push, the merge, any non-read gh): later reads go to GitHub. `mergeable` is never
// served from it, since GitHub recomputes it after every push. If the combined read fails or is garbled, every check
// falls back to its own read, so each keeps its own fail-open rule.

export const SNAPSHOT_FIELDS = ['baseRefName', 'body', 'isDraft', 'files', 'headRefName', 'statusCheckRollup']
const SERVED = new Set(SNAPSHOT_FIELDS)
const PR_URL = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/\d+$/
const GH_READS = new Set(['view', 'list', 'status', 'checks', 'diff'])
const GIT_WRITES = new Set(['push'])

function writes(cmd, args) {
  if (cmd === 'gh') {
    if (args[0] === 'api') return args.some((a, i) => (a === '-X' || a === '--method') && String(args[i + 1]).toUpperCase() !== 'GET') || args.includes('-f') || args.includes('-F') || args.includes('--input')
    return !GH_READS.has(args[1])
  }
  if (cmd === 'git') return GIT_WRITES.has(args[0])
  return false
}

// The fields of a `gh pr view <url> --json a,b` this snapshot can answer, or null.
function servable(prUrl, cmd, args) {
  if (cmd !== 'gh' || args.length !== 5 || args[0] !== 'pr' || args[1] !== 'view' || args[2] !== prUrl || args[3] !== '--json') return null
  const fields = String(args[4]).split(',').map((f) => f.trim()).filter(Boolean)
  return fields.length && fields.every((f) => SERVED.has(f)) ? fields : null
}

export function snapshotExec(prUrl, exec) {
  if (typeof prUrl !== 'string' || !PR_URL.test(prUrl)) return exec
  let snap = null    // Promise<object|null> of the combined read
  let open = true    // false after the first write
  return async (cmd, args = [], ...rest) => {
    const fields = open ? servable(prUrl, cmd, args) : null
    if (!fields) {
      if (writes(cmd, args)) open = false
      return exec(cmd, args, ...rest)
    }
    if (!snap) {
      snap = exec('gh', ['pr', 'view', prUrl, '--json', SNAPSHOT_FIELDS.join(',')], ...rest)
        .then(({ stdout }) => {
          const v = JSON.parse(stdout)
          return v && typeof v === 'object' && SNAPSHOT_FIELDS.every((f) => f in v) ? v : null
        })
        .catch(() => null)
    }
    const v = await snap
    if (!v || !open) return exec(cmd, args, ...rest)
    return { stdout: JSON.stringify(Object.fromEntries(fields.map((f) => [f, v[f]]))), stderr: '' }
  }
}

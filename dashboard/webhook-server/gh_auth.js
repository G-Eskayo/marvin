import { readFileSync } from 'fs'
import path from 'path'

// Export GH_TOKEN from ~/.claude/.gh-token so the `gh pr merge` and
// `git push --force-with-lease` this server's children run authenticate from the
// SAME credential the ticket pipeline uses (task_dispatch.py exports it the same
// way), not from each machine's own `gh auth login`.
//
// Why: found 2026-10-02 -- the laptop's own gh login had expired ("The token in
// default is invalid") and every Approve routed to its webhook failed, with
// nothing saying why. Never overrides an explicitly-set GH_TOKEN, and leaves the
// environment alone when there's no usable file so gh falls back to its own
// login. Returns where the credential came from -- never the value itself.
export function loadGhToken(env = process.env, home = process.env.HOME, read = (p) => readFileSync(p, 'utf8')) {
  if (env.GH_TOKEN) return 'env'
  try {
    const token = String(read(path.join(home, '.claude', '.gh-token'))).trim()
    if (token) {
      env.GH_TOKEN = token
      return 'file'
    }
  } catch {
    // missing/unreadable: fall through to gh's own stored login
  }
  return 'none'
}

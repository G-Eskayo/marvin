import { execFileSync } from 'child_process'
import { readFileSync } from 'fs'
import { homedir } from 'os'
import { join } from 'path'

// A GUI-launched app (login item, `open -a`, Finder double-click) inherits
// launchd's minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), not the shell
// profile PATH -- so `gh` (installed via Homebrew, in .zshrc's PATH export,
// not .zprofile) is invisible to execFile even though it works fine from a
// terminal. Fix: ask the user's actual interactive login shell for its real
// PATH once at startup and adopt it, rather than hardcoding a Homebrew
// prefix that would break on an Intel Mac (/usr/local/bin) or wherever `gh`
// lands on a future machine. Best-effort: on failure, leaves the inherited
// PATH alone rather than crashing startup over it.
export function adoptLoginShellPath(env = process.env, exec = execFileSync) {
  try {
    const out = exec('/bin/zsh', ['-ilc', 'echo -n "$PATH"'], {
      encoding: 'utf8',
      timeout: 8000
    })
    if (out && out.trim()) {
      env.PATH = out.trim()
    }
  } catch {
    // Best effort -- fall back to whatever PATH launchd/Finder handed us.
  }
}

// Every machine keeps one working GitHub credential in ~/.claude/.gh-token (health checks verify it); gh's own
// keychain login can be expired or absent (the laptop's was invalid, so the Docs tab failed there). Child
// processes inherit GH_TOKEN, so adopting the shared token once at startup fixes every gh call at the root.
// An explicit GH_TOKEN in the environment wins.
export function adoptSharedGhToken(env = process.env, read = (p) => readFileSync(p, 'utf8'), home = homedir()) {
  if (env.GH_TOKEN) return false
  try {
    const token = read(join(home, '.claude', '.gh-token')).trim()
    if (!token) return false
    env.GH_TOKEN = token
    return true
  } catch {
    return false
  }
}

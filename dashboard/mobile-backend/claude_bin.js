import { execSync } from 'child_process'
import { existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Candidates tried when PATH lookup fails. Mirrors lib/claude_bin.py.
export function getCandidates() {
  return [
    path.join(homedir(), '.local', 'bin', 'claude'),
    '/opt/homebrew/bin/claude',
    '/usr/local/bin/claude'
  ]
}

// Simple which implementation: try to execute which command.
export function defaultWhichFn(bin) {
  try {
    const result = execSync(`which ${bin}`, { encoding: 'utf8' })
    return result.trim()
  } catch {
    return null
  }
}

// Resolve claude binary: try which-style PATH lookup, fall back to common install locations.
// launchd services don't source .zshrc/.zprofile, so PATH is limited to system defaults
// (e.g., /usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin). Homebrew installs often go to
// /opt/homebrew/bin; npm-installed binaries go to ~/.local/bin. Both miss the default PATH,
// so a plain lookup would fail silently, leaving the service unable to spawn claude.
// Throws Error if not found anywhere.
export function resolveClaudeBin(whichFn = defaultWhichFn, candidatesFn = getCandidates, existsFn = existsSync) {
  try {
    const found = whichFn('claude')
    if (found) {
      return found
    }
  } catch {
    // which threw; continue to fallback
  }

  for (const candidate of candidatesFn()) {
    if (existsFn(candidate)) {
      return candidate
    }
  }

  throw new Error(
    'claude CLI not found on PATH or in common install locations ' +
    '(~/.local/bin, /opt/homebrew/bin, /usr/local/bin)'
  )
}

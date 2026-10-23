import { existsSync, statSync, realpathSync, mkdirSync, appendFileSync, readFileSync, writeFileSync, readdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { varPath } from './marvin_paths.js'

// Keeps clean local clones current so the Docs search sees what is on GitHub (#611, Gil 2026-10-22: clarity-captions
// was 24 commits behind and "Parakeet" found nothing). A clone is fast-forwarded only when it is on its default branch,
// has no work in it (staged, unstaged or untracked, ignoring .claude/ agent folders), has no rebase/merge/cherry-pick in
// progress and is not ahead of origin: `git fetch` then `git merge --ff-only`. Never reset, never force. A clone that is
// mid-work is left alone and reported mid-work, so its docs are searched from the GitHub saved copy (docs_service.js).
// Never touched: the shared ~/.agents checkout (auto-sync owns it), any git worktree, and any repo with an Xcode
// project (*.xcodeproj, *.xcworkspace or XcodeGen's project.yml; Gil, 2026-10-22, #618).
//
// Cost: per project at most once per `minIntervalMs` (30 min): one bounded Xcode-marker walk (1-10 ms on the real
// clones), 4-5 local git commands (~10 ms each) and, for a clean
// clone only, one `git fetch` (network) and possibly one fast-forward. Nothing polls: it runs when the Docs tab opens
// and on the docs change watch. Memory O(projects); the log is trimmed to its last `maxLogLines` lines.

const MID_OPS = ['rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'BISECT_LOG']
const IGNORED_UNTRACKED = ['.claude/'] // agent worktrees and settings: never someone's work in the repo
export const MID_WORK = new Set(['dirty', 'other-branch', 'ahead', 'diverged', 'mid-operation'])

const out = async (exec, dir, args) => String((await exec('git', ['-C', dir, ...args], { timeout: 60_000 })).stdout).trim()

async function defaultBranch(exec, dir) {
  try {
    return (await out(exec, dir, ['symbolic-ref', '--short', 'refs/remotes/origin/HEAD'])).replace(/^origin\//, '')
  } catch {
    for (const b of ['main', 'master']) {
      try {
        await out(exec, dir, ['rev-parse', '--verify', '--quiet', `refs/remotes/origin/${b}`])
        return b
      } catch {
        // try the next one
      }
    }
    return null
  }
}

// { status: 'current' | 'behind' | 'dirty' | 'other-branch' | 'ahead' | 'diverged' | 'mid-operation' | 'worktree' |
//   'not-a-clone' | 'no-upstream', branch, base, ahead, behind }. Local only: reads the last-fetched origin refs.
export async function cloneState(dir, exec) {
  const dotGit = path.join(dir, '.git')
  if (!existsSync(dotGit)) return { status: 'not-a-clone' }
  if (!statSync(dotGit).isDirectory()) return { status: 'worktree' }
  if (MID_OPS.some((f) => existsSync(path.join(dotGit, f)))) return { status: 'mid-operation' }
  const base = await defaultBranch(exec, dir)
  if (!base) return { status: 'no-upstream' }
  let branch = null
  try {
    branch = await out(exec, dir, ['symbolic-ref', '--short', '-q', 'HEAD'])
  } catch {
    branch = null // detached HEAD
  }
  if (branch !== base) return { status: 'other-branch', branch, base }
  const lines = (await out(exec, dir, ['status', '--porcelain=v1', '--untracked-files=normal'])).split('\n').filter(Boolean)
  const work = lines.filter((l) => !(l.startsWith('?? ') && IGNORED_UNTRACKED.some((p) => l.slice(3).startsWith(p))))
  if (work.length) return { status: 'dirty', branch, base }
  const [ahead, behind] = (await out(exec, dir, ['rev-list', '--left-right', '--count', `HEAD...refs/remotes/origin/${base}`])).split(/\s+/).map(Number)
  const status = ahead && behind ? 'diverged' : ahead ? 'ahead' : behind ? 'behind' : 'current'
  return { status, branch, base, ahead, behind }
}

// Gil, 2026-10-22 (#618): never update a repo that has an Xcode project. The first marker found, or null: a
// `*.xcodeproj` or `*.xcworkspace`, or an XcodeGen `project.yml` (the .xcodeproj it generates is often not committed).
// On disk, committed or not. Walks at most `maxDepth` levels and `maxEntries` entries, skipping hidden folders (.git,
// .claude agent worktrees) and build/dependency folders: O(entries) readdir calls, bounded.
const SKIP_DIRS = new Set(['node_modules', 'build', 'DerivedData', 'Pods', 'Carthage', 'dist', 'out', 'venv'])
export function findXcodeMarker(dir, { maxDepth = 4, maxEntries = 20_000 } = {}) {
  const stack = [[dir, 0]]
  let seen = 0
  while (stack.length && seen < maxEntries) {
    const [d, depth] = stack.pop()
    let entries
    try {
      entries = readdirSync(d, { withFileTypes: true })
    } catch {
      continue
    }
    for (const e of entries) {
      seen++
      if (e.name.endsWith('.xcodeproj') || e.name.endsWith('.xcworkspace') || (e.name === 'project.yml' && e.isFile())) {
        return path.relative(dir, path.join(d, e.name))
      }
      if (e.isDirectory() && !e.name.startsWith('.') && !SKIP_DIRS.has(e.name) && depth < maxDepth) stack.push([path.join(d, e.name), depth + 1])
    }
  }
  return null
}

const real = (p) => {
  try {
    return realpathSync(p)
  } catch {
    return path.resolve(p)
  }
}

export function createCloneFreshener({
  exec,
  home = homedir(),
  logPath = varPath('clone-freshen.jsonl'),
  now = Date.now,
  minIntervalMs = 30 * 60 * 1000,
  maxLogLines = 500,
  xcodeMarker = (dir) => findXcodeMarker(dir)
}) {
  const lastRun = new Map() // dir -> ms
  const mid = new Map() // dir -> true when mid-work at the last look
  const shared = real(path.join(home, '.agents'))

  function log(entry) {
    try {
      mkdirSync(path.dirname(logPath), { recursive: true })
      appendFileSync(logPath, `${JSON.stringify({ t: new Date(now()).toISOString(), ...entry })}\n`)
      const lines = readFileSync(logPath, 'utf8').split('\n').filter(Boolean)
      if (lines.length > maxLogLines) writeFileSync(logPath, `${lines.slice(-maxLogLines).join('\n')}\n`)
    } catch {
      // an unwritable log never stops the update
    }
  }

  async function one(rec, dir) {
    const project = rec.id
    const marker = xcodeMarker(dir)
    if (marker) {
      mid.set(dir, true) // searched from its saved GitHub copy, like a mid-work clone
      log({ project, dir, result: 'left-alone', status: 'xcode-project', marker })
      return false
    }
    let st = await cloneState(dir, exec)
    if (st.status === 'worktree' || st.status === 'not-a-clone' || st.status === 'no-upstream') return false
    if (MID_WORK.has(st.status)) {
      mid.set(dir, true)
      log({ project, dir, result: 'left-alone', status: st.status })
      return false
    }
    try {
      await out(exec, dir, ['fetch', '--quiet', 'origin'])
    } catch (err) {
      log({ project, dir, result: 'fetch-failed', error: String(err?.message || err).slice(0, 200) })
      return false
    }
    st = await cloneState(dir, exec)
    if (MID_WORK.has(st.status)) {
      mid.set(dir, true)
      log({ project, dir, result: 'left-alone', status: st.status })
      return false
    }
    mid.set(dir, false)
    if (st.status !== 'behind') return false
    const from = await out(exec, dir, ['rev-parse', 'HEAD'])
    try {
      await out(exec, dir, ['merge', '--ff-only', '--quiet', `refs/remotes/origin/${st.base}`])
    } catch (err) {
      // e.g. an ignored .claude/ file in the way: git refused, nothing changed
      mid.set(dir, true)
      log({ project, dir, result: 'ff-refused', error: String(err?.message || err).slice(0, 200) })
      return false
    }
    const to = await out(exec, dir, ['rev-parse', 'HEAD'])
    log({ project, dir, result: 'fast-forwarded', from, to, commits: st.behind })
    return true
  }

  return {
    // Runs every due project; returns { updated: [ids fast-forwarded], midWork: [ids left alone with work in them] }.
    // Never throws.
    async freshen(projects) {
      const due = []
      for (const rec of projects || []) {
        if (!rec?.repo) continue
        const dir = (rec.localPaths || []).find((p) => existsSync(p))
        if (!dir || real(dir) === shared) continue
        const last = lastRun.get(dir)
        if (last != null && now() - last < minIntervalMs) continue
        lastRun.set(dir, now()) // claimed before any await, so an overlapping call skips it
        due.push([rec, dir])
      }
      const updated = []
      const midWork = []
      for (const [rec, dir] of due) {
        try {
          if (await one(rec, dir)) updated.push(rec.id)
          if (mid.get(dir) === true) midWork.push(rec.id)
        } catch (err) {
          log({ project: rec.id, dir, result: 'error', error: String(err?.message || err).slice(0, 200) })
        }
      }
      return { updated, midWork }
    },
    // True when the clone had work in it at the last look: search its saved GitHub copy instead.
    midWork: (dir) => mid.get(dir) === true
  }
}

import { readdirSync, readFileSync, writeFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Per-project execution profiles (lib/project_profile.py, config/projects/*.json). The dashboard only
// needs to know which projects opted in to having their PRs approved or denied from MR Review.
export const PROFILES_DIR = path.join(homedir(), '.agents', 'config', 'projects')

export function readMergeableRepos(dir = PROFILES_DIR) {
  const repos = new Set()
  let names = []
  try {
    names = readdirSync(dir).filter((n) => n.endsWith('.json'))
  } catch {
    return repos
  }
  for (const n of names) {
    try {
      const p = JSON.parse(readFileSync(path.join(dir, n), 'utf-8'))
      if (p && p.repo && p.merge_from_dashboard === true) repos.add(p.repo)
    } catch {
      // one broken profile must not hide the others
    }
  }
  return repos
}

function readAll(dir) {
  let names = []
  try {
    names = readdirSync(dir).filter((n) => n.endsWith('.json')).sort()
  } catch {
    return []
  }
  const out = []
  for (const n of names) {
    try {
      const file = path.join(dir, n)
      const profile = JSON.parse(readFileSync(file, 'utf-8'))
      if (profile && profile.repo) out.push({ file, profile })
    } catch {
      // one broken profile must not hide the others
    }
  }
  return out
}

// What the Health tab shows for each project that has an execution profile (lib/project_profile.py).
export function listProfiles(dir = PROFILES_DIR) {
  return readAll(dir).map(({ profile: p }) => ({
    repo: p.repo,
    name: p.repo.split('/').pop(),
    dispatch: p.dispatch === 'on' ? 'on' : 'off',
    mergeFromDashboard: p.merge_from_dashboard === true,
    machines: p.machines || [],
    cloneMode: p.clone_mode || 'catalog',
    checks: (p.verify || []).map((t) => ({ label: t.label || t.id, required: !!t.required, enabled: t.enabled !== false }))
  }))
}

// Flips ONLY the dispatch value in the profile's text, so the notes and layout a person wrote are untouched.
export function setDispatch(repo, value, dir = PROFILES_DIR) {
  if (value !== 'on' && value !== 'off') throw new Error('Dispatch can only be set to on or off')
  const hit = readAll(dir).find(({ profile }) => profile.repo === repo)
  if (!hit) throw new Error(`No profile for ${repo}`)
  const text = readFileSync(hit.file, 'utf-8')
  const re = /("dispatch"\s*:\s*)"(?:on|off)"/
  if (!re.test(text)) throw new Error(`${repo}'s profile has no dispatch setting to change`)
  writeFileSync(hit.file, text.replace(re, `$1"${value}"`))
}

// Flips ONLY the merge_from_dashboard value in the profile's text, preserving the rest.
export function setMergeFromDashboard(repo, value, dir = PROFILES_DIR) {
  if (typeof value !== 'boolean') throw new Error('merge_from_dashboard can only be set to true or false')
  const hit = readAll(dir).find(({ profile }) => profile.repo === repo)
  if (!hit) throw new Error(`No profile for ${repo}`)
  const text = readFileSync(hit.file, 'utf-8')
  const re = /("merge_from_dashboard"\s*:\s*)(?:true|false)/
  if (!re.test(text)) throw new Error(`${repo}'s profile has no merge_from_dashboard setting to change`)
  writeFileSync(hit.file, text.replace(re, `$1${value}`))
}

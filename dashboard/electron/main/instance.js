import { readFileSync } from 'fs'
import { execFileSync } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// Whose MARVIN is this? The dashboard's twin of lib/instance.py (ADR 0071); same rules, same tests' shape.
// The engine is public and shared; each person's state is a private instance at ~/.agents/instance/. Nothing here
// hard-codes an owner: a friend's dashboard must show and file tickets against their own fork.
//   engineRepo()   the engine checkout's GitHub `origin` > instance.json "engine_repo" (or raises NotConfigured)
//   owner()        instance.json "owner" > the owner part of engineRepo() (or raises NotConfigured)
//   ticketsRepo()  instance.json "tickets_repo" > engineRepo() (or raises NotConfigured)
//   featureEnabled(name)  only a real `true` in instance.json "features" turns one on
// Raises NotConfigured when there is no git origin and no instance.json config. This is a configuration error,
// not a runtime error — call sites should fail loudly (show UI) rather than silently falling back.
// A corrupt or wrong-shaped instance.json is a blank instance. Values are computed once per process
// (O(1) after); reset() forgets them. MARVIN_ENGINE_DIR / MARVIN_INSTANCE_DIR override the locations (tests).

export const UPSTREAM = 'G-Eskayo/marvin'
const GITHUB = /github\.com[:/]+([A-Za-z0-9-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\/?$/

export class NotConfigured extends Error {
  constructor(msg) {
    super(msg || 'MARVIN instance is not configured: no git origin and no instance.json')
    this.name = 'NotConfigured'
  }
}

export const engineDir = (env = process.env) => env.MARVIN_ENGINE_DIR || path.join(homedir(), '.agents')
export const instanceDir = (env = process.env) => env.MARVIN_INSTANCE_DIR || path.join(engineDir(env), 'instance')
export const instancePath = (...parts) => path.join(instanceDir(), ...parts)

let cache = null

function load() {
  if (cache) return cache
  let config = {}
  try {
    const data = JSON.parse(readFileSync(path.join(instanceDir(), 'instance.json'), 'utf8'))
    if (data && typeof data === 'object' && !Array.isArray(data)) config = data
  } catch {}
  let origin = null
  try {
    const url = execFileSync('git', ['-C', engineDir(), 'remote', 'get-url', 'origin'], { encoding: 'utf8', timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'] }).trim()
    const m = GITHUB.exec(url)
    if (m) origin = `${m[1]}/${m[2]}`
  } catch {}
  cache = { config, origin }
  return cache
}

const str = (key) => {
  const v = load().config[key]
  return typeof v === 'string' && v.trim() ? v : null
}

export const engineRepo = () => {
  const origin = load().origin
  if (origin) return origin
  const configured = str('engine_repo')
  if (configured) return configured
  throw new NotConfigured(
    'No git origin found, and no engine_repo in instance.json. ' +
    'Is MARVIN_INSTANCE_DIR set correctly? Are you in a git clone with origin?'
  )
}

export const owner = () => {
  const configured = str('owner')
  if (configured) return configured
  return engineRepo().split('/')[0]
}

export const ticketsRepo = () => {
  const configured = str('tickets_repo')
  if (configured) return configured
  return engineRepo()
}

export function featureEnabled(name) {
  const f = load().config.features
  return !!f && typeof f === 'object' && !Array.isArray(f) && f[name] === true
}

export function reset() {
  cache = null
}

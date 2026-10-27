import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs'
import { execFileSync } from 'child_process'
import { homedir } from 'os'
import path from 'path'
import { supportRole } from './support.js'

// Whose MARVIN is this? The dashboard's twin of lib/instance.py (ADR 0071); same rules, same tests' shape.
// The engine is public and shared; each person's state is a private instance at ~/.agents/instance/. Nothing here
// hard-codes an owner: a friend's dashboard must show and file tickets against their own fork.
//   engineRepo()   the engine checkout's GitHub `origin` > instance.json "engine_repo" > the upstream
//   owner()        instance.json "owner" > the owner part of engineRepo()
//   ticketsRepo()  instance.json "tickets_repo" > engineRepo()
//   featureEnabled(name)  only a real `true` in instance.json "features" turns one on
// A missing, corrupt or wrong-shaped instance.json is a blank instance. Values are computed once per process
// (O(1) after); reset() forgets them. MARVIN_ENGINE_DIR / MARVIN_INSTANCE_DIR override the locations (tests).

export const UPSTREAM = 'G-Eskayo/marvin'
const GITHUB = /github\.com[:/]+([A-Za-z0-9-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\/?$/

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

export const engineRepo = () => load().origin || str('engine_repo') || UPSTREAM
export const owner = () => str('owner') || engineRepo().split('/')[0]
export const ticketsRepo = () => str('tickets_repo') || engineRepo()

export function featureEnabled(name) {
  const f = load().config.features
  return !!f && typeof f === 'object' && !Array.isArray(f) && f[name] === true
}

// The support link (ADR 0073): { role: 'helped' | 'helper' | null, repos } from instance.json's "support" block.
export const support = () => supportRole(load().config)

export function reset() {
  cache = null
}

const KNOWN_ADDONS = ['portfolio', 'resume_tailor', 'seal_ingest']

export function createInstanceHandlers() {
  return {
    features: async () => {
      const features = load().config.features || {}
      return {
        portfolio: features.portfolio === true,
        resume_tailor: features.resume_tailor === true,
        seal_ingest: features.seal_ingest === true
      }
    },
    setFeature: async (_event, name, value) => {
      if (!KNOWN_ADDONS.includes(name)) {
        throw new Error(`Unknown add-on: ${name}`)
      }
      const config = load().config
      if (!config.features) {
        config.features = {}
      }
      config.features[name] = value
      // Write back to instance.json
      const configPath = path.join(instanceDir(), 'instance.json')
      const dir = path.dirname(configPath)
      if (!existsSync(dir)) {
        mkdirSync(dir, { recursive: true })
      }
      writeFileSync(configPath, JSON.stringify(config, null, 2))
      reset()  // Clear cache so next read gets fresh data
      return { ok: true }
    }
  }
}

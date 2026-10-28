import { readFileSync } from 'fs'
import { execFileSync } from 'child_process'
import { homedir } from 'os'
import path from 'path'

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

export function reset() {
  cache = null
}

// ── feature gates (ADR 0074) ────────────────────────────────────────────────

const KNOWN_ADDONS = ['portfolio', 'resume_tailor', 'seal_ingest']

export function getFeatures() {
  const f = load().config.features || {}
  return KNOWN_ADDONS.reduce((acc, name) => {
    acc[name] = featureEnabled(name)
    return acc
  }, {})
}

export function setFeature(name, value) {
  if (!KNOWN_ADDONS.includes(name)) {
    throw new Error(`Unknown add-on: ${name}. Known add-ons: ${KNOWN_ADDONS.join(', ')}`)
  }

  const { writeFileSync } = require('fs')
  const path = require('path')
  const configPath = instancePath('instance.json')

  let config = load().config
  if (!config.features || typeof config.features !== 'object' || Array.isArray(config.features)) {
    config.features = {}
  }

  config.features[name] = !!value

  // Write atomically via temp file
  const tmpPath = path.join(instanceDir(), `.instance.json.tmp`)
  writeFileSync(tmpPath, JSON.stringify(config, null, 2) + '\n')
  require('fs').renameSync(tmpPath, configPath)

  reset()
}

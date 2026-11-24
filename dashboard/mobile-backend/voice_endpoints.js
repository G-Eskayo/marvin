// Endpoints that may talk to the voice endpoint, with their abilities (CONTEXT.md "Endpoints and the brief"):
// show, touch, listen, speak. A new endpoint (a Dot in the kitchen) is a new entry in
// ~/.claude/voice-endpoints.json, not new code.
import { existsSync, readFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

export const ABILITIES = ['show', 'touch', 'listen', 'speak']

const DEFAULT_ENDPOINTS = {
  homepod: { abilities: ['listen', 'speak'] },
  mac: { abilities: ['show', 'touch', 'listen', 'speak'] },
  iphone: { abilities: ['show', 'touch', 'listen', 'speak'] },
  watch: { abilities: ['show', 'touch', 'listen', 'speak'] },
  appletv: { abilities: ['show', 'listen', 'speak'] }
}

export const DEFAULT_ENDPOINTS_PATH = path.join(homedir(), '.claude', 'voice-endpoints.json')

function cleanAbilities(list) {
  return Array.isArray(list) ? ABILITIES.filter((a) => list.includes(a)) : []
}

export function loadEndpoints({ path: file = DEFAULT_ENDPOINTS_PATH } = {}) {
  const endpoints = Object.create(null)
  for (const [name, ep] of Object.entries(DEFAULT_ENDPOINTS)) endpoints[name] = { abilities: [...ep.abilities] }
  if (!existsSync(file)) return endpoints
  try {
    const extra = JSON.parse(readFileSync(file, 'utf-8'))?.endpoints || {}
    for (const [name, ep] of Object.entries(extra)) {
      const key = name.toLowerCase()
      if (!/^[a-z0-9][a-z0-9_-]{0,40}$/.test(key)) continue
      endpoints[key] = { abilities: cleanAbilities(ep?.abilities) }
    }
  } catch (err) {
    console.error(`voice-endpoints: ignoring malformed ${file}: ${err.message}`)
  }
  return endpoints
}

// The endpoint a request names, or null if it isn't registered. Client-sent abilities can only narrow the
// registered ones.
export function resolveEndpoint(endpoints, source, requestedAbilities) {
  if (typeof source !== 'string' || !source) return null
  const name = source.toLowerCase()
  if (!Object.prototype.hasOwnProperty.call(endpoints, name)) return null
  const registered = endpoints[name].abilities
  const abilities = Array.isArray(requestedAbilities)
    ? registered.filter((a) => requestedAbilities.includes(a))
    : [...registered]
  return { name, abilities }
}

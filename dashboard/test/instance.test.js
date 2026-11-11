import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from 'fs'
import { execFileSync } from 'child_process'
import { tmpdir } from 'os'
import path from 'path'
import * as inst from '../electron/main/instance.js'

// ADR 0071: the dashboard's "whose MARVIN is this?". Same rules as lib/instance.py, tried the same hard ways:
// forks, odd remote URLs, stale or corrupt configs, string "false" flags. Temp dirs only, never the real ~/.agents.

let root, saved
const at = ({ origin = null, config } = {}) => {
  const engine = mkdtempSync(path.join(root, 'engine-'))
  execFileSync('git', ['init', '-q', engine])
  if (origin) execFileSync('git', ['-C', engine, 'remote', 'add', 'origin', origin])
  const dir = mkdtempSync(path.join(root, 'inst-'))
  if (config !== undefined) writeFileSync(path.join(dir, 'instance.json'), typeof config === 'string' ? config : JSON.stringify(config))
  process.env.MARVIN_ENGINE_DIR = engine
  process.env.MARVIN_INSTANCE_DIR = dir
  inst.reset()
  return dir
}

beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'instance-test-'))
  saved = { e: process.env.MARVIN_ENGINE_DIR, i: process.env.MARVIN_INSTANCE_DIR }
})
afterEach(() => {
  for (const [k, v] of [['MARVIN_ENGINE_DIR', saved.e], ['MARVIN_INSTANCE_DIR', saved.i]]) v === undefined ? delete process.env[k] : (process.env[k] = v)
  inst.reset()
  rmSync(root, { recursive: true, force: true })
})

describe('instance', () => {
  it.each([
    'https://github.com/pat-example/marvin.git',
    'git@github.com:pat-example/marvin.git',
    'ssh://git@github.com/pat-example/marvin.git',
    'https://x-access-token:abc@github.com/pat-example/marvin',
  ])('derives the engine repo and owner from origin %s', (url) => {
    at({ origin: url })
    expect(inst.engineRepo()).toBe('pat-example/marvin')
    expect(inst.owner()).toBe('pat-example')
  })

  it('lets the real origin beat a stale engine_repo copied into the config', () => {
    at({ origin: 'https://github.com/pat-example/marvin.git', config: { engine_repo: 'G-Eskayo/marvin' } })
    expect(inst.engineRepo()).toBe('pat-example/marvin')
  })

  it('falls back to the config, then the upstream, with no usable origin', () => {
    at({ origin: '/srv/mirror/marvin.git', config: { engine_repo: 'pat-example/marvin' } })
    expect(inst.engineRepo()).toBe('pat-example/marvin')
    at({ config: {} })
    expect(inst.engineRepo()).toBe(inst.UPSTREAM)
  })

  it('takes the person from the config when the fork is org-owned', () => {
    at({ origin: 'https://github.com/some-org/marvin.git', config: { owner: 'pat-example' } })
    expect(inst.owner()).toBe('pat-example')
  })

  it('sends tickets to the engine repo unless the instance says otherwise', () => {
    at({ origin: 'https://github.com/pat-example/marvin.git' })
    expect(inst.ticketsRepo()).toBe('pat-example/marvin')
    at({ origin: 'https://github.com/pat-example/marvin.git', config: { tickets_repo: 'pat-example/marvin-instance' } })
    expect(inst.ticketsRepo()).toBe('pat-example/marvin-instance')
  })

  it('switches a feature on only for a real true', () => {
    at({ config: { features: { a: 'false', b: 'yes', c: 1, d: true } } })
    expect(['a', 'b', 'c', 'd', 'missing'].map(inst.featureEnabled)).toEqual([false, false, false, true, false])
  })

  it.each(['{not json', '[]', '"a string"', '{"features": "yes"}', '{"features": [true]}', '{"owner": 7}'])(
    'reads a corrupt or wrong-shaped config (%s) as a blank instance', (bad) => {
      at({ origin: 'https://github.com/pat-example/marvin.git', config: bad })
      expect(inst.owner()).toBe('pat-example')
      expect(inst.featureEnabled('portfolio')).toBe(false)
    })

  it('treats a missing instance dir as a blank instance', () => {
    at({})
    process.env.MARVIN_INSTANCE_DIR = path.join(root, 'nope')
    inst.reset()
    expect(inst.featureEnabled('portfolio')).toBe(false)
    expect(inst.instancePath('plans', 'x.md')).toBe(path.join(root, 'nope', 'plans', 'x.md'))
  })

  it('reads the config once per process until reset', () => {
    const dir = at({ config: { owner: 'pat-example' } })
    expect(inst.owner()).toBe('pat-example')
    writeFileSync(path.join(dir, 'instance.json'), JSON.stringify({ owner: 'changed' }))
    expect(inst.owner()).toBe('pat-example')
    inst.reset()
    expect(inst.owner()).toBe('changed')
  })

  it('puts the instance inside the engine checkout by default', () => {
    delete process.env.MARVIN_INSTANCE_DIR
    process.env.MARVIN_ENGINE_DIR = '/x/engine'
    expect(inst.instanceDir()).toBe(path.join('/x/engine', 'instance'))
  })
})

describe('setFeature', () => {
  it('successfully sets a feature to true', async () => {
    at({ config: {} })
    const handlers = inst.createInstanceHandlers()
    const result = await handlers.setFeature(null, 'portfolio', true)
    expect(result).toEqual({ ok: true })
    expect(inst.featureEnabled('portfolio')).toBe(true)
  })

  it('successfully sets a feature to false', async () => {
    at({ config: { features: { portfolio: true } } })
    const handlers = inst.createInstanceHandlers()
    const result = await handlers.setFeature(null, 'portfolio', false)
    expect(result).toEqual({ ok: true })
    expect(inst.featureEnabled('portfolio')).toBe(false)
  })

  it('throws on unknown add-on', async () => {
    at({ config: {} })
    const handlers = inst.createInstanceHandlers()
    await expect(handlers.setFeature(null, 'unknown', true)).rejects.toThrow('Unknown add-on')
  })

  it('refuses to write when the config file is corrupt (unparseable JSON)', async () => {
    at({ config: '{not json' })
    const handlers = inst.createInstanceHandlers()
    await expect(handlers.setFeature(null, 'portfolio', true)).rejects.toThrow('corrupted or invalid')
  })

  it('refuses to write when the config file is invalid (wrong shape)', async () => {
    at({ config: '[]' })
    const handlers = inst.createInstanceHandlers()
    await expect(handlers.setFeature(null, 'portfolio', true)).rejects.toThrow('corrupted or invalid')
  })

  it('guards features to a plain object when it is null', async () => {
    at({ config: { features: null } })
    const handlers = inst.createInstanceHandlers()
    const result = await handlers.setFeature(null, 'portfolio', true)
    expect(result).toEqual({ ok: true })
    expect(inst.featureEnabled('portfolio')).toBe(true)
  })

  it('guards features to a plain object when it is a string', async () => {
    at({ config: { features: 'yes' } })
    const handlers = inst.createInstanceHandlers()
    const result = await handlers.setFeature(null, 'portfolio', true)
    expect(result).toEqual({ ok: true })
    expect(inst.featureEnabled('portfolio')).toBe(true)
  })

  it('guards features to a plain object when it is an array', async () => {
    at({ config: { features: [true] } })
    const handlers = inst.createInstanceHandlers()
    const result = await handlers.setFeature(null, 'portfolio', true)
    expect(result).toEqual({ ok: true })
    expect(inst.featureEnabled('portfolio')).toBe(true)
  })

  it('creates instance.json if it does not exist', async () => {
    const dir = at({})
    const handlers = inst.createInstanceHandlers()
    const result = await handlers.setFeature(null, 'portfolio', true)
    expect(result).toEqual({ ok: true })
    expect(inst.featureEnabled('portfolio')).toBe(true)
  })

  it('creates instance dir if it does not exist', async () => {
    const root = mkdtempSync(path.join(tmpdir(), 'instance-test-'))
    const engine = mkdtempSync(path.join(root, 'engine-'))
    execFileSync('git', ['init', '-q', engine])
    const instDir = path.join(root, 'nonexistent', 'inst')
    process.env.MARVIN_ENGINE_DIR = engine
    process.env.MARVIN_INSTANCE_DIR = instDir
    inst.reset()
    const handlers = inst.createInstanceHandlers()
    const result = await handlers.setFeature(null, 'portfolio', true)
    expect(result).toEqual({ ok: true })
    expect(inst.featureEnabled('portfolio')).toBe(true)
    rmSync(root, { recursive: true, force: true })
  })

  it('resets cache after write so the next read gets fresh data', async () => {
    at({ config: { owner: 'pat' } })
    expect(inst.owner()).toBe('pat')
    const handlers = inst.createInstanceHandlers()
    await handlers.setFeature(null, 'portfolio', true)
    // Change the file on disk (simulating an external write)
    const configPath = inst.instancePath('instance.json')
    writeFileSync(configPath, JSON.stringify({ owner: 'changed', features: { portfolio: true } }))
    // Without reset, we'd still see 'pat'; with it, we see 'changed'
    expect(inst.owner()).toBe('changed')
  })

  it('multiple calls in sequence work independently', async () => {
    at({ config: {} })
    const handlers = inst.createInstanceHandlers()
    await handlers.setFeature(null, 'portfolio', true)
    expect(inst.featureEnabled('portfolio')).toBe(true)
    await handlers.setFeature(null, 'resume_tailor', true)
    expect(inst.featureEnabled('portfolio')).toBe(true)
    expect(inst.featureEnabled('resume_tailor')).toBe(true)
    await handlers.setFeature(null, 'portfolio', false)
    expect(inst.featureEnabled('portfolio')).toBe(false)
    expect(inst.featureEnabled('resume_tailor')).toBe(true)
  })
})

describe('dashboard readers point at the instance (ADR 0071 step 2)', () => {
  it('reads run results and project profiles from the private instance, not the public engine', async () => {
    process.env.MARVIN_INSTANCE_DIR = path.join(root, 'inst')
    const { vi } = await import('vitest')
    vi.resetModules()
    const metrics = await import('../electron/main/metrics.js')
    const profiles = await import('../electron/main/profiles.js')
    expect(metrics.DEFAULT_METRICS_DIR).toBe(path.join(root, 'inst', 'bench', 'metrics'))
    expect(profiles.PROFILES_DIR).toBe(path.join(root, 'inst', 'config', 'projects'))
  })
})

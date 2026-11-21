import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { isSideEffectRequest, planFor, chooseBrain } from '../mobile-backend/voice_router.js'
import { loadEndpoints, resolveEndpoint } from '../mobile-backend/voice_endpoints.js'

describe('isSideEffectRequest', () => {
  it.each([
    'merge 657',
    'MARVIN, merge PR 657',
    'please approve the voice PR',
    'can you close ticket 12?',
    'could you deploy the portfolio',
    'send Noah an email saying hi',
    'delete the old worktrees',
    'restart the mobile backend',
    'go ahead and push it',
    'reply to ticket 670 with yes',
    'turn off the lights',
    'open a ticket for the HomePod bug',
    'file a bug about the Siri doorway'
  ])('treats %j as a side effect', (text) => {
    expect(isSideEffectRequest(text)).toBe(true)
  })

  it.each([
    'what did we merge today?',
    'did 657 get merged',
    'how many PRs are open',
    'is main green',
    "what's the weather",
    'tell me a joke',
    'hello MARVIN',
    'which tickets are blocked?',
    'when was the last deploy'
  ])('treats %j as a question', (text) => {
    expect(isSideEffectRequest(text)).toBe(false)
  })

  it('a polite request phrased as a question is still a side effect', () => {
    expect(isSideEffectRequest('can you merge 657')).toBe(true)
    expect(isSideEffectRequest('would you send the brief to my phone')).toBe(true)
  })
})

describe('planFor', () => {
  it('restates the request as a plan that sends confirmation to the phone', () => {
    expect(planFor('MARVIN, can you merge PR 657 please?')).toBe("I'd merge PR 657. Confirm on your phone.")
  })

  it('makes something speakable from a request that is only filler', () => {
    expect(planFor('please')).toMatch(/confirm on your phone/i)
  })
})

describe('chooseBrain', () => {
  const noHits = () => ({ intent: 'architecture', hits: 0 })
  const twoHits = () => ({ intent: 'research', hits: 2 })

  it('sends a side-effect request to the phone, whatever the classifier says', async () => {
    expect((await chooseBrain('merge 657', { classify: noHits })).kind).toBe('action')
  })

  it('short small talk with no classifier hits goes to the fast brain', async () => {
    expect((await chooseBrain('hello there', { classify: noHits })).kind).toBe('fast')
  })

  it('a request the route classifier recognises goes to the deep brain', async () => {
    const r = await chooseBrain('research the latest papers on turn detection', { classify: twoHits })
    expect(r).toMatchObject({ kind: 'deep', intent: 'research' })
  })

  it('a long request goes deep even with no classifier hits', async () => {
    const long = 'so I was thinking about the thing we talked about yesterday with the house and the speakers and how it should all work together'
    expect((await chooseBrain(long, { classify: noHits })).kind).toBe('deep')
  })

  it('a look-up about MARVIN state goes deep (the fast brain has no tools)', async () => {
    expect((await chooseBrain('is main green', { classify: noHits })).kind).toBe('deep')
    expect((await chooseBrain('how many PRs are open', { classify: noHits })).kind).toBe('deep')
  })

  it('a classifier that throws or hangs does not stop the turn', async () => {
    const r1 = await chooseBrain('hello', { classify: () => { throw new Error('boom') } })
    expect(r1.kind).toBe('fast')
    const r2 = await chooseBrain('hello', { classify: () => new Promise(() => {}), classifyTimeoutMs: 20 })
    expect(r2.kind).toBe('fast')
  })
})

describe('voice endpoints registry', () => {
  it('knows the HomePod, Mac, iPhone, Watch and Apple TV by default, with their abilities', () => {
    const eps = loadEndpoints({ path: '/nonexistent/voice-endpoints.json' })
    expect(Object.keys(eps).sort()).toEqual(['appletv', 'homepod', 'iphone', 'mac', 'watch'])
    expect(eps.homepod.abilities).toEqual(['listen', 'speak'])
    expect(eps.iphone.abilities).toContain('show')
  })

  it('a new endpoint is a config entry, not code', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'voice-eps-'))
    const file = path.join(dir, 'voice-endpoints.json')
    writeFileSync(file, JSON.stringify({ endpoints: { 'kitchen-dot': { abilities: ['listen', 'speak'] } } }))
    const eps = loadEndpoints({ path: file })
    expect(eps['kitchen-dot'].abilities).toEqual(['listen', 'speak'])
    expect(eps.homepod).toBeDefined()
  })

  it('a malformed config falls back to the defaults', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'voice-eps-'))
    const file = path.join(dir, 'voice-endpoints.json')
    writeFileSync(file, '{not json')
    expect(loadEndpoints({ path: file }).homepod).toBeDefined()
  })

  it('an unknown or missing source resolves to null', () => {
    const eps = loadEndpoints({ path: '/nonexistent' })
    expect(resolveEndpoint(eps, 'toaster')).toBeNull()
    expect(resolveEndpoint(eps, '')).toBeNull()
    expect(resolveEndpoint(eps, undefined)).toBeNull()
    expect(resolveEndpoint(eps, '__proto__')).toBeNull()
    expect(resolveEndpoint(eps, 'constructor')).toBeNull()
  })

  it('a client can narrow its abilities but never add one the registry lacks', () => {
    const eps = loadEndpoints({ path: '/nonexistent' })
    expect(resolveEndpoint(eps, 'HomePod', ['listen', 'speak', 'show']).abilities).toEqual(['listen', 'speak'])
    expect(resolveEndpoint(eps, 'iphone', ['speak']).abilities).toEqual(['speak'])
  })
})

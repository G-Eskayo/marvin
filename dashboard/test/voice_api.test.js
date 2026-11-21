import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtemp, rm } from 'fs/promises'
import { readFileSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createVoiceApiRouter, createVoiceApprovalHandler } from '../mobile-backend/voice_api.js'
import { createThreadStore } from '../mobile-backend/thread_store.js'
import { createPendingActionsStore } from '../mobile-backend/pending_actions.js'
import { loadEndpoints } from '../mobile-backend/voice_endpoints.js'

class MockRequest {
  constructor(method, url, body, headers = {}) {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost', ...headers }
    this.body = body
  }
  async *[Symbol.asyncIterator]() {
    if (this.body !== undefined) yield Buffer.from(typeof this.body === 'string' ? this.body : JSON.stringify(this.body))
  }
}

class MockResponse {
  constructor() { this.statusCode = null; this.headers = {}; this.chunks = []; this.ended = false }
  writeHead(code, headers = {}) { this.statusCode = code; this.headers = headers; return this }
  write(c) { this.chunks.push(String(c)); return true }
  end(c) { if (c !== undefined) this.write(c); this.ended = true; return this }
  json() { return JSON.parse(this.chunks.join('')) }
  events() { return this.chunks.join('').split('\n').filter(Boolean).map((l) => JSON.parse(l)) }
}

function fastReplying(...tokens) {
  return async function* () { for (const t of tokens) yield t }
}
function fastFailing(msg = 'connect ECONNREFUSED 127.0.0.1:11434') {
  // eslint-disable-next-line require-yield
  return async function* () { throw new Error(msg) }
}
function deepReplying(text, { sessionId = 'sess-1', delayMs = 0 } = {}) {
  const calls = []
  const fn = async function* (args) {
    calls.push(args)
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs))
    yield { type: 'session', sessionId }
    for (const piece of text.match(/.{1,7}/gs) || []) yield { type: 'text', text: piece }
    yield { type: 'result', text, sessionId, isError: false }
  }
  fn.calls = calls
  return fn
}
function deepFailing() {
  const calls = []
  const fn = async function* (args) {
    calls.push(args)
    yield { type: 'error', message: 'Failed to spawn claude: ENOENT' }
  }
  fn.calls = calls
  return fn
}

let dir, threadStore, pendingActionStore, logPath
beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'voice-api-'))
  threadStore = createThreadStore({ path: path.join(dir, 'thread.json') })
  pendingActionStore = createPendingActionsStore({ path: path.join(dir, 'pending.json') })
  logPath = path.join(dir, 'voice-turns.jsonl')
})
afterEach(async () => { await rm(dir, { recursive: true, force: true }) })

function router(overrides = {}) {
  return createVoiceApiRouter({
    threadStore,
    pendingActionStore,
    endpoints: loadEndpoints({ path: path.join(dir, 'none.json') }),
    classify: async () => ({ intent: 'architecture', hits: 0 }),
    fastBrain: fastReplying('Hello Gil.'),
    runSession: deepReplying('Main is green.'),
    logPath,
    deepWaitMs: 2000,
    ...overrides
  })
}

async function post(r, body, headers) {
  const req = new MockRequest('POST', '/voice', body, headers)
  const res = new MockResponse()
  const handled = await r(req, res)
  return { handled, res }
}

const turnsLogged = () => (existsSync(logPath) ? readFileSync(logPath, 'utf-8').trim().split('\n').filter(Boolean).map(JSON.parse) : [])

describe('POST /voice — refusals, each still speakable', () => {
  it('ignores routes that are not its own', async () => {
    const res = new MockResponse()
    expect(await router()(new MockRequest('GET', '/thread'), res)).toBe(false)
  })

  it('refuses an unknown device', async () => {
    const { res } = await post(router(), { text: 'hello', source: 'toaster' })
    expect(res.statusCode).toBe(403)
    expect(res.json()).toMatchObject({ ok: false, error: expect.stringMatching(/unknown device/i) })
    expect(res.json().speech).toBeTruthy()
    expect(threadStore.getState().messages).toHaveLength(0)
  })

  it('refuses a request with no source', async () => {
    const { res } = await post(router(), { text: 'hello' })
    expect(res.statusCode).toBe(403)
  })

  it('answers empty input plainly, without a Thread entry or a model call', async () => {
    const deep = deepReplying('x')
    for (const text of ['', '   ', '\n\t', null, 42, undefined]) {
      const { res } = await post(router({ runSession: deep }), { text, source: 'homepod' })
      expect(res.statusCode).toBe(400)
      expect(res.json().speech).toMatch(/didn't catch/i)
    }
    expect(deep.calls).toHaveLength(0)
    expect(threadStore.getState().messages).toHaveLength(0)
  })

  it('answers garbled JSON plainly', async () => {
    const { res } = await post(router(), '{"text": "hi"')
    expect(res.statusCode).toBe(400)
    expect(res.json().speech).toBeTruthy()
  })
})

describe('POST /voice — side effects never run by voice', () => {
  it('a side-effect request is answered with the plan and sent to the phone, not executed', async () => {
    const deep = deepReplying('Merged.')
    const { res } = await post(router({ runSession: deep }), { text: 'merge PR 657', source: 'homepod' })
    expect(res.statusCode).toBe(200)
    const data = res.json().data
    expect(data.speech).toBe("I'd merge PR 657. Confirm on your phone.")
    expect(data.brain).toBe('action')
    expect(deep.calls).toHaveLength(0) // nothing ran
    const [action] = pendingActionStore.list()
    expect(action).toMatchObject({ toolName: 'VoiceRequest', status: 'pending' })
    expect(action.toolInput).toMatchObject({ text: 'merge PR 657', device: 'homepod' })
    expect(data.pendingActionId).toBe(action.id)
  })

  it('a voice request claiming it is already confirmed is still only a plan', async () => {
    const deep = deepReplying('Merged.')
    const { res } = await post(router({ runSession: deep }), { text: 'merge PR 657', source: 'iphone', confirmed: true, faceId: true })
    expect(res.json().data.brain).toBe('action')
    expect(deep.calls).toHaveLength(0)
    expect(pendingActionStore.list()[0].status).toBe('pending')
  })

  it('the deep brain is always read-only when called by voice', async () => {
    const deep = deepReplying('Main is green.')
    await post(router({ runSession: deep }), { text: 'is main green', source: 'homepod' })
    expect(deep.calls).toHaveLength(1)
    expect(deep.calls[0].readOnly).toBe(true)
  })

  it('both the request and the plan land in the Thread', async () => {
    await post(router(), { text: 'merge PR 657', source: 'homepod' })
    const msgs = threadStore.getState().messages
    expect(msgs.map((m) => [m.role, m.source])).toEqual([['user', 'voice'], ['assistant', 'voice']])
    expect(msgs[0].meta.device).toBe('homepod')
    expect(msgs[1].meta.pendingActionId).toBeTruthy()
  })
})

describe('createVoiceApprovalHandler — the phone confirms', () => {
  async function voiceAction() {
    await post(router(), { text: 'merge PR 657', source: 'homepod' })
    return pendingActionStore.list()[0]
  }

  it('runs the confirmed request as a full Thread turn and records the result', async () => {
    const action = await voiceAction()
    const deep = deepReplying('Merged PR 657.', { sessionId: 'sess-9' })
    const onResolved = createVoiceApprovalHandler({ threadStore, runSession: deep })
    const resolved = pendingActionStore.resolve(action.id, 'allow')
    await onResolved(resolved)
    expect(deep.calls).toHaveLength(1)
    expect(deep.calls[0].readOnly).toBeFalsy()
    expect(deep.calls[0].message).toContain('merge PR 657')
    expect(threadStore.getState().messages.at(-1)).toMatchObject({ role: 'assistant', text: 'Merged PR 657.', sessionId: 'sess-9' })
    expect(threadStore.currentSession()).toBe('sess-9')
  })

  it('a denial runs nothing', async () => {
    const action = await voiceAction()
    const deep = deepReplying('Merged.')
    await createVoiceApprovalHandler({ threadStore, runSession: deep })(pendingActionStore.resolve(action.id, 'deny'))
    expect(deep.calls).toHaveLength(0)
    expect(threadStore.getState().messages.at(-1).text).toMatch(/cancel/i)
  })

  it('an approval that comes too late runs nothing', async () => {
    const action = await voiceAction()
    const deep = deepReplying('Merged.')
    const handler = createVoiceApprovalHandler({ threadStore, runSession: deep, maxAgeMs: 1000, now: () => action.createdAt + 5000 })
    await handler(pendingActionStore.resolve(action.id, 'allow'))
    expect(deep.calls).toHaveLength(0)
    expect(threadStore.getState().messages.at(-1).text).toMatch(/expired|too long ago/i)
  })

  it('ignores actions that are not voice requests (the tool-permission hook owns those)', async () => {
    const deep = deepReplying('x')
    const a = pendingActionStore.create({ toolName: 'Bash', toolInput: { command: 'ls' }, summary: 'Run shell command', sessionId: 's' })
    await createVoiceApprovalHandler({ threadStore, runSession: deep })(pendingActionStore.resolve(a.id, 'allow'))
    expect(deep.calls).toHaveLength(0)
  })

  it('a still-pending action runs nothing', async () => {
    const action = await voiceAction()
    const deep = deepReplying('x')
    await createVoiceApprovalHandler({ threadStore, runSession: deep })(action)
    expect(deep.calls).toHaveLength(0)
  })
})

describe('POST /voice — fast brain', () => {
  it('small talk is answered by the fast brain and lands in the Thread', async () => {
    const deep = deepReplying('x')
    const { res } = await post(router({ runSession: deep }), { text: 'hello', source: 'homepod' })
    expect(res.json().data).toMatchObject({ speech: 'Hello Gil.', brain: 'fast' })
    expect(deep.calls).toHaveLength(0)
    expect(threadStore.getState().messages.map((m) => m.text)).toEqual(['hello', 'Hello Gil.'])
  })

  it('the fast brain handing up with DEEP sends the turn to the deep brain, and DEEP is never spoken', async () => {
    const deep = deepReplying('Here is the deep answer.')
    const { res } = await post(router({ fastBrain: fastReplying('DE', 'EP'), runSession: deep }), { text: 'hi', source: 'homepod' })
    const data = res.json().data
    expect(data.brain).toBe('deep')
    expect(data.speech).not.toMatch(/DEEP/)
    expect(data.speech).toContain('Here is the deep answer.')
  })

  it.each([['deep'], ['Deep.'], ['  DEEP\n'], ['de', 'ep'], ['DEEP', '.']])('the hand-up word in any form (%j) is never spoken', async (...tokens) => {
    const deep = deepReplying('Deep answer.')
    const { res } = await post(router({ fastBrain: fastReplying(...tokens), runSession: deep }), { text: 'tell me a joke', source: 'homepod' })
    expect(res.json().data.brain).toBe('deep')
    expect(res.json().data.speech).toBe('Deep answer.')
  })

  it('a reply that merely starts with the letters of the hand-up word is spoken', async () => {
    const { res } = await post(router({ fastBrain: fastReplying('Deeply sorry, Gil.') }), { text: 'hello', source: 'homepod' })
    expect(res.json().data).toMatchObject({ brain: 'fast', speech: 'Deeply sorry, Gil.' })
  })

  it('a fast brain that is down hands the turn to the deep brain', async () => {
    const deep = deepReplying('Deep says hi.')
    const { res } = await post(router({ fastBrain: fastFailing(), runSession: deep }), { text: 'hello', source: 'homepod' })
    expect(res.json().data).toMatchObject({ brain: 'deep' })
    expect(res.json().data.speech).toContain('Deep says hi.')
  })

  it('a fast brain that writes Markdown and URLs comes out speakable', async () => {
    const { res } = await post(router({ fastBrain: fastReplying('**Sure**, see [this](https://x.com/a) or https://example.org/b.') }), { text: 'hey', source: 'homepod' })
    const speech = res.json().data.speech
    expect(speech).not.toMatch(/\*|\[|\]|https?:|\(/)
  })
})

describe('POST /voice — deep brain', () => {
  it('a look-up goes to the deep brain, framed for voice and resuming the Thread session', async () => {
    threadStore.setCurrentSession('sess-0')
    const deep = deepReplying('Main is green.', { sessionId: 'sess-0' })
    const { res } = await post(router({ runSession: deep }), { text: 'is main green', source: 'homepod' })
    expect(res.json().data).toMatchObject({ brain: 'deep' })
    expect(res.json().data.speech).toContain('Main is green.')
    expect(deep.calls[0].sessionId).toBe('sess-0')
    expect(deep.calls[0].message).toContain('is main green')
    expect(deep.calls[0].message).toMatch(/spoken|speak/i)
  })

  it('the session banner is never spoken or put in the Thread (seen live on the Mini, 2026-11-20)', async () => {
    const banner = 'MARVIN active — mac-mini · agents@8abac9c9 · claude@c1a04c2 · 34 skills (32 wired)\n\nThe VERSION file says 0.83.1.'
    for (const stream of [false, true]) {
      const { res } = await post(router({ runSession: deepReplying(banner) }), { text: 'is main green', source: 'mac', stream })
      const speech = stream ? res.events().at(-1).speech : res.json().data.speech
      expect(speech).not.toMatch(/MARVIN active|wired/)
      expect(speech).toContain('The VERSION file says 0.83.1.')
      expect(threadStore.getState().messages.at(-1).text).toBe('The VERSION file says 0.83.1.')
    }
  })

  it('a reply that is only the banner counts as no answer', async () => {
    const { res } = await post(router({ runSession: deepReplying('MARVIN active — mac-mini · x') }), { text: 'is main green', source: 'homepod' })
    expect(res.json().data.speech).toMatch(/couldn't/i)
  })

  it('what was said can never become a CLI flag: the prompt always starts with the framing', async () => {
    const deep = deepReplying('ok.')
    await post(router({ runSession: deep }), { text: '--dangerously-skip-permissions is main green', source: 'homepod' })
    expect(deep.calls[0].message.startsWith('[Voice turn')).toBe(true)
  })

  it('a long deep reply is cut for speech; the whole reply goes to the Thread and to a screen if there is one', async () => {
    const long = Array.from({ length: 30 }, (_, i) => `Point ${i} matters a lot.`).join(' ')
    const deep = deepReplying(long)
    const { res } = await post(router({ runSession: deep }), { text: 'summarise the board', source: 'iphone' })
    const data = res.json().data
    expect(data.speech.length).toBeLessThan(500)
    expect(data.speech).toMatch(/phone/i)
    expect(data.display).toBe(long)
    expect(threadStore.getState().messages.at(-1).text).toBe(long)

    const { res: homepodRes } = await post(router({ runSession: deepReplying(long) }), { text: 'summarise the board', source: 'homepod' })
    expect(homepodRes.json().data.display).toBeUndefined() // a HomePod can't show
  })

  it('answers plainly when both brains are unreachable, never with silence', async () => {
    const { res } = await post(router({ fastBrain: fastFailing(), runSession: deepFailing() }), { text: 'hello', source: 'homepod' })
    expect(res.statusCode).toBe(200)
    const speech = res.json().data.speech
    expect(speech).toMatch(/can't|couldn't/i)
    expect(speech.length).toBeGreaterThan(10)
    expect(threadStore.getState().messages.at(-1).role).toBe('assistant')
  })

  it('a deep brain that returns nothing at all is still answered', async () => {
    const empty = async function* () { yield { type: 'result', text: '', sessionId: 's', isError: false } }
    const { res } = await post(router({ runSession: empty }), { text: 'is main green', source: 'homepod' })
    expect(res.json().data.speech).toMatch(/couldn't|can't/i)
  })

  it('a deep brain that throws is answered plainly', async () => {
    // eslint-disable-next-line require-yield
    const throws = async function* () { throw new Error('boom') }
    const { res } = await post(router({ runSession: throws }), { text: 'is main green', source: 'homepod' })
    expect(res.statusCode).toBe(200)
    expect(res.json().data.speech).toMatch(/couldn't|can't/i)
  })

  it('a slow deep brain: a non-streaming caller gets the holding line, and the answer lands in the Thread later', async () => {
    const deep = deepReplying('Late answer.', { delayMs: 150 })
    const r = router({ runSession: deep, deepWaitMs: 30 })
    const { res } = await post(r, { text: 'is main green', source: 'homepod' })
    const data = res.json().data
    expect(data.brain).toBe('deep')
    expect(data.deepPending).toBe(true)
    expect(data.speech).toMatch(/phone/i)
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect(threadStore.getState().messages.at(-1).text).toBe('Late answer.')
  })
})

describe('POST /voice — streaming', () => {
  it('streams a holding line first, then each deep sentence as it finishes, then done', async () => {
    const deep = deepReplying('First thing. Second thing. Third thing.')
    const { res } = await post(router({ runSession: deep }), { text: 'is main green', source: 'mac', stream: true })
    expect(res.headers['Content-Type']).toBe('application/x-ndjson')
    const evts = res.events()
    expect(evts[0]).toMatchObject({ type: 'turn', brain: 'deep' })
    const sentences = evts.filter((e) => e.type === 'sentence')
    expect(sentences[0].holding).toBe(true)
    expect(sentences.slice(1).map((s) => s.text)).toEqual(['First thing.', 'Second thing.', 'Third thing.'])
    expect(evts.at(-1)).toMatchObject({ type: 'done' })
    expect(evts.at(-1).timings.firstSentenceMs).toBeGreaterThanOrEqual(0)
  })

  it('a streamed long reply stops speaking after the cap and says where the rest is', async () => {
    const long = Array.from({ length: 30 }, (_, i) => `Point ${i} matters.`).join(' ')
    const { res } = await post(router({ runSession: deepReplying(long) }), { text: 'is main green', source: 'mac', stream: true })
    const spoken = res.events().filter((e) => e.type === 'sentence' && !e.holding)
    expect(spoken.length).toBeLessThanOrEqual(4)
    expect(spoken.at(-1).text).toMatch(/phone/i)
  })

  it('a streamed failure still ends with something to say', async () => {
    const { res } = await post(router({ fastBrain: fastFailing(), runSession: deepFailing() }), { text: 'hello', source: 'mac', stream: true })
    const evts = res.events()
    expect(evts.some((e) => e.type === 'sentence' && /can't|couldn't/i.test(e.text))).toBe(true)
    expect(evts.at(-1).type).toBe('done')
    expect(res.ended).toBe(true)
  })

  it('a streamed action emits the plan and the pending action id', async () => {
    const { res } = await post(router(), { text: 'merge 657', source: 'mac', stream: true })
    const evts = res.events()
    expect(evts.find((e) => e.type === 'pending').actionId).toBe(pendingActionStore.list()[0].id)
  })
})

describe('POST /voice — measurement', () => {
  it('logs time per stage for every turn, with the client-reported speech-to-text time', async () => {
    await post(router(), { text: 'hello', source: 'homepod', sttMs: 420 })
    const [turn] = turnsLogged()
    expect(turn).toMatchObject({ device: 'homepod', brain: 'fast', sttMs: 420 })
    for (const k of ['routingMs', 'firstTokenMs', 'firstSentenceMs', 'totalMs']) expect(typeof turn[k]).toBe('number')
    expect(turn.turnId).toBeTruthy()
    expect(turn.text).toBeUndefined() // the log holds timings, not what was said
  })

  it('takes the first-sound time from the device afterwards', async () => {
    const { res } = await post(router(), { text: 'hello', source: 'homepod' })
    const turnId = res.json().data.turnId
    const r = router()
    const timingRes = new MockResponse()
    await r(new MockRequest('POST', '/voice/timing', { turnId, firstSoundMs: 640 }), timingRes)
    expect(timingRes.statusCode).toBe(200)
    expect(turnsLogged().at(-1)).toMatchObject({ turnId, firstSoundMs: 640 })
  })

  it('rejects a timing report with no turn id or a nonsense time', async () => {
    for (const body of [{ firstSoundMs: 1 }, { turnId: 'x', firstSoundMs: -5 }, { turnId: 'x', firstSoundMs: 'soon' }]) {
      const res = new MockResponse()
      await router()(new MockRequest('POST', '/voice/timing', body), res)
      expect(res.statusCode).toBe(400)
    }
  })

  it('a log that cannot be written never breaks the turn', async () => {
    const { res } = await post(router({ logPath: '/nonexistent-dir/x/voice.jsonl' }), { text: 'hello', source: 'homepod' })
    expect(res.json().data.speech).toBe('Hello Gil.')
  })
})

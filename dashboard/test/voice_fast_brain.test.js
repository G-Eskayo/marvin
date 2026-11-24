import { describe, it, expect, afterEach } from 'vitest'
import { createServer } from 'http'
import { streamFastBrain, ESCALATE, isEscalation } from '../mobile-backend/fast_brain.js'
import { routeClassify } from '../mobile-backend/route_classify.js'

let server
afterEach(() => new Promise((r) => (server ? server.close(() => r()) : r())))

function listen(handler) {
  return new Promise((resolve) => {
    server = createServer(handler)
    server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`))
  })
}

async function collect(gen) {
  const out = []
  for await (const t of gen) out.push(t)
  return out
}

describe('streamFastBrain', () => {
  it('streams the local model token by token, sending the system prompt and history', async () => {
    let seen
    const url = await listen(async (req, res) => {
      let body = ''
      for await (const c of req) body += c
      seen = JSON.parse(body)
      res.writeHead(200, { 'Content-Type': 'application/x-ndjson' })
      res.write(JSON.stringify({ message: { content: 'Hi ' } }) + '\n')
      res.write(JSON.stringify({ message: { content: 'Gil.' } }) + '\n')
      res.end(JSON.stringify({ done: true }) + '\n')
    })
    const tokens = await collect(streamFastBrain({ text: 'hello', history: [{ role: 'user', text: 'earlier' }], baseUrl: url, model: 'm' }))
    expect(tokens.join('')).toBe('Hi Gil.')
    expect(seen.model).toBe('m')
    expect(seen.stream).toBe(true)
    expect(seen.keep_alive).toBeTruthy()
    expect(seen.messages[0].role).toBe('system')
    expect(seen.messages.at(-1)).toEqual({ role: 'user', content: 'hello' })
    expect(seen.messages.some((m) => m.content === 'earlier')).toBe(true)
  })

  it('throws when the model server is down (connection refused)', async () => {
    await expect(collect(streamFastBrain({ text: 'hi', baseUrl: 'http://127.0.0.1:1', firstTokenTimeoutMs: 500 }))).rejects.toThrow()
  })

  it('throws on a non-200 reply (e.g. the model is not pulled)', async () => {
    const url = await listen((req, res) => res.writeHead(404).end('{"error":"model not found"}'))
    await expect(collect(streamFastBrain({ text: 'hi', baseUrl: url }))).rejects.toThrow(/404|not found/)
  })

  it('gives up when the first token does not arrive in time, so the turn is not silent', async () => {
    const url = await listen(() => {}) // accepts, never answers
    const started = Date.now()
    await expect(collect(streamFastBrain({ text: 'hi', baseUrl: url, firstTokenTimeoutMs: 100 }))).rejects.toThrow(/first token/i)
    expect(Date.now() - started).toBeLessThan(2000)
  })

  it('surfaces a model-reported error in the stream', async () => {
    const url = await listen((req, res) => { res.writeHead(200); res.end(JSON.stringify({ error: 'out of memory' }) + '\n') })
    await expect(collect(streamFastBrain({ text: 'hi', baseUrl: url }))).rejects.toThrow(/out of memory/)
  })

  it('exports the escalation word the fast brain uses to hand a turn up', () => {
    expect(ESCALATE).toBe('DEEP')
  })

  it('recognises the hand-up word in any case, with punctuation, but not inside another word', () => {
    for (const r of ['DEEP', 'deep', 'Deep.', ' DEEP\n', '"DEEP"']) expect(isEscalation(r)).toBe(true)
    for (const r of ['Deeply sorry.', 'A deep question.', '', null]) expect(isEscalation(r)).toBe(false)
  })

  it('sends worked examples to the small model, ending each with an assistant turn', async () => {
    let seen
    const url = await listen(async (req, res) => {
      let body = ''
      for await (const c of req) body += c
      seen = JSON.parse(body)
      res.writeHead(200); res.end(JSON.stringify({ done: true }) + '\n')
    })
    await collect(streamFastBrain({ text: 'hi', baseUrl: url }))
    const examples = seen.messages.slice(1, -1)
    expect(examples.length).toBeGreaterThanOrEqual(2)
    expect(examples.some((m) => m.role === 'assistant' && m.content === 'DEEP')).toBe(true)
  })
})

describe('streamFastBrain — whose assistant', () => {
  async function promptFor(name) {
    let seen
    const url = await listen(async (req, res) => {
      let body = ''
      for await (const c of req) body += c
      seen = JSON.parse(body)
      res.writeHead(200); res.end(JSON.stringify({ done: true }) + '\n')
    })
    await collect(streamFastBrain({ text: 'hi', baseUrl: url, name }))
    await new Promise((r) => server.close(() => r()))
    server = null
    return JSON.stringify(seen.messages)
  }

  it('greets the person by the name the instance gives, and by no name otherwise', async () => {
    expect(await promptFor('Pat')).toContain('Hello Pat.')
    const anonymous = await promptFor(null)
    expect(anonymous).toContain('Hello. What can I do for you?')
    expect(anonymous).not.toMatch(/\bGil\b/)
  })
})

describe('routeClassify', () => {
  it('runs the route classifier and returns its intent and hit count', async () => {
    const r = await routeClassify('research the latest arxiv papers on turn detection')
    expect(r.intent).toBe('research')
    expect(r.hits).toBeGreaterThanOrEqual(2)
  })

  it('returns null rather than throwing when the classifier cannot run', async () => {
    expect(await routeClassify('hello', { python: '/nonexistent/python' })).toBeNull()
  })
})

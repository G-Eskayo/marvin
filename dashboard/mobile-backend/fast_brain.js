// The fast brain (ADR 0075 point 5): a small local model, kept warm in Ollama, that answers small talk itself and
// hands anything bigger up by replying with the single word DEEP.
import http from 'http'
import { ownerName as instanceOwnerName } from '../electron/main/instance.js'

export const ESCALATE = 'DEEP'
export const DEFAULT_FAST_MODEL = process.env.MARVIN_VOICE_FAST_MODEL || 'qwen2.5:3b'
export const DEFAULT_OLLAMA_URL = process.env.OLLAMA_HOST_URL || 'http://127.0.0.1:11434'
const KEEP_ALIVE = '60m' // stays loaded between turns so the first word comes inside the 1 s budget

// A small model needs structure and an example, not a long preamble (ADR 0085 point 1). Checked against qwen2.5:3b
// on the Mini, 2026-11-20: without the examples it answered in single lower-case words and said "deep" for a joke.
function systemPrompt(now = new Date(), name = null) {
  return [
    `You are MARVIN, a personal assistant, talking out loud to ${name || 'the person you work for'}.`,
    'Reply with one or two short, complete, friendly spoken sentences in normal capitalisation.',
    'No Markdown, no lists, no URLs. You have no tools and no live data.',
    `It is ${now.toLocaleString('en-US', { dateStyle: 'full', timeStyle: 'short' })}.`,
    `If answering needs live data, their projects, tickets, email, calendar, the web, or taking an action, reply with`,
    `only the word ${ESCALATE}.`
  ].join(' ')
}

const examples = (name) => [
  ['hello', `Hello${name ? ` ${name}` : ''}. What can I do for you?`],
  ["what's on my calendar tomorrow", ESCALATE],
  ['how many legs does a spider have', 'A spider has eight legs.']
]

// True when a fast-brain reply is the hand-up word, in any case, with or without punctuation.
export function isEscalation(reply) {
  return new RegExp(`^\\W*${ESCALATE}\\b`, 'i').test(String(reply || ''))
}

// Async generator of text tokens. Throws if the server is down, replies non-200, reports an error, or sends no
// first token within firstTokenTimeoutMs.
export async function* streamFastBrain({
  text,
  history = [],
  model = DEFAULT_FAST_MODEL,
  baseUrl = DEFAULT_OLLAMA_URL,
  firstTokenTimeoutMs = 1500,
  totalTimeoutMs = 15000,
  now,
  name = instanceOwnerName()
} = {}) {
  const messages = [
    { role: 'system', content: systemPrompt(now, name) },
    ...examples(name).flatMap(([user, assistant]) => [{ role: 'user', content: user }, { role: 'assistant', content: assistant }]),
    ...history.slice(-6).map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: String(m.text || '') })),
    { role: 'user', content: String(text) }
  ]
  const body = JSON.stringify({ model, messages, stream: true, keep_alive: KEEP_ALIVE, options: { num_predict: 120 } })
  const url = new URL('/api/chat', baseUrl)

  const res = await new Promise((resolve, reject) => {
    const req = http.request(
      { hostname: url.hostname, port: url.port, path: url.pathname, method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } },
      resolve
    )
    req.setTimeout(firstTokenTimeoutMs, () => req.destroy(new Error(`fast brain: no first token in ${firstTokenTimeoutMs} ms`)))
    req.on('error', reject)
    req.end(body)
  })

  if (res.statusCode !== 200) {
    let detail = ''
    for await (const c of res) detail += c
    throw new Error(`fast brain: HTTP ${res.statusCode} ${detail.slice(0, 200)}`)
  }

  const deadline = Date.now() + totalTimeoutMs
  let buffer = ''
  for await (const chunk of res) {
    if (Date.now() > deadline) { res.destroy(); throw new Error('fast brain: reply took too long') }
    buffer += chunk
    let nl
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (!line) continue
      let evt
      try { evt = JSON.parse(line) } catch { continue }
      if (evt.error) throw new Error(`fast brain: ${evt.error}`)
      if (evt.message?.content) yield evt.message.content
      if (evt.done) return
    }
  }
}

// Load the model now so the first spoken turn isn't a cold start. Best effort.
export function warmFastBrain({ model = DEFAULT_FAST_MODEL, baseUrl = DEFAULT_OLLAMA_URL } = {}) {
  const body = JSON.stringify({ model, keep_alive: KEEP_ALIVE })
  const url = new URL('/api/generate', baseUrl)
  return new Promise((resolve) => {
    const req = http.request({ hostname: url.hostname, port: url.port, path: url.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, (res) => {
      res.resume()
      res.on('end', () => resolve(res.statusCode === 200))
    })
    req.on('error', () => resolve(false))
    req.end(body)
  })
}

// The voice endpoint (ADR 0075): the one place spoken words reach MARVIN. Words in, a reply written to be spoken
// out, every exchange in the Thread. The Siri doorway, the Mac voice loop, the iPhone Voice surface and any later
// endpoint (Apple TV, a Dot) call it, naming themselves in `source`.
//
//   POST /voice          { text, source, abilities?, sttMs?, stream? }
//   POST /voice/timing   { turnId, firstSoundMs }
//
// Side effects never run on a voice request (ADR 0005, ADR 0043): the reply is the plan, and the request waits in
// /pending-actions for the phone, where Face ID confirms it. The deep brain runs read-only when voice calls it.
import { appendFileSync, mkdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { randomUUID } from 'crypto'
import { performance } from 'perf_hooks'
import { runSession } from './session_runner.js'
import { streamFastBrain, ESCALATE, isEscalation } from './fast_brain.js'
import { routeClassify } from './route_classify.js'
import { chooseBrain, planFor } from './voice_router.js'
import { loadEndpoints, resolveEndpoint } from './voice_endpoints.js'
import { toSpeakable, capSpoken, createSentenceStream } from './speakable.js'
import { ownerName } from '../electron/main/instance.js'

export const VOICE_REQUEST_TOOL = 'VoiceRequest'
export const DEFAULT_VOICE_LOG = path.join(homedir(), '.claude', 'logs', 'voice-turns.jsonl')

const MAX_BODY_BYTES = 64 * 1024
const MAX_TEXT_CHARS = 4000
const SPOKEN_CAP = { maxSentences: 3, maxChars: 400 }

const SAY = {
  garbled: "Sorry, that request came through garbled. Try again.",
  empty: "I didn't catch anything. Try again.",
  unknownDevice: "I don't know this device, so I can't answer it.",
  tooLong: "That was too long for me to take in by voice. Try it in Chat.",
  restOnPhone: "I'll put the answer in the Thread on your phone.",
  bothDown: "Sorry, I can't reach my models right now. Try again in a minute.",
  deepFailed: "I couldn't get an answer to that just now. Try again, or ask in Chat.",
  internal: "Something went wrong on my side. Try again."
}

const HOLDING = {
  research: 'Let me look into that.',
  recall: 'Let me check my notes.',
  coding: 'Let me look at the code.'
}

function voiceFraming(device) {
  return [
    `[Voice turn from the ${device}. Your reply is spoken aloud: answer in at most three short sentences of plain`,
    'speech, with no Markdown, lists, code or URLs. You cannot take actions from voice. If this asks for one, say',
    'what you would do and that it needs confirming on the phone.]'
  ].join(' ')
}

function sendJson(res, status, payload) {
  res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(payload))
  return true
}

async function readBody(req) {
  let body = ''
  for await (const chunk of req) {
    body += chunk.toString()
    if (body.length > MAX_BODY_BYTES) return { tooLarge: true }
  }
  return { body }
}

function writeLog(logPath, record) {
  try {
    mkdirSync(path.dirname(logPath), { recursive: true })
    appendFileSync(logPath, JSON.stringify(record) + '\n')
  } catch (err) {
    console.error(`voice: could not write ${logPath}: ${err.message}`)
  }
}

// The session-start identity banner (global CLAUDE.md, "MARVIN active — ...") is for a terminal, never to be spoken.
export function stripBanner(text) {
  return String(text || '').replace(/^[ \t]*MARVIN active —[^\n]*(\n+|$)/gm, '')
}

const BANNER = 'MARVIN active —'

// Streaming version: holds text back only while it might still be the banner, then drops the banner line.
function createBannerGate() {
  let held = ''
  let open = false
  return (piece) => {
    if (open) return piece
    held += piece
    const lead = held.trimStart()
    if (lead.length < BANNER.length && BANNER.startsWith(lead)) return ''
    if (lead.startsWith(BANNER)) {
      const nl = held.indexOf('\n')
      if (nl < 0) return ''
      held = held.slice(nl).replace(/^\n+/, '')
    }
    open = true
    const out = held
    held = ''
    return out
  }
}

const ms = (t0, t) => (t == null ? null : Math.round(t - t0))

export function createVoiceApiRouter(opts = {}) {
  const threadStore = opts.threadStore
  const pendingActionStore = opts.pendingActionStore
  if (!threadStore || !pendingActionStore) throw new Error('threadStore and pendingActionStore are required')
  const getEndpoints = () => opts.endpoints || loadEndpoints()
  const classify = opts.classify === undefined ? routeClassify : opts.classify
  const fastBrain = opts.fastBrain || streamFastBrain
  const runSessionFn = opts.runSession || runSession
  const logPath = opts.logPath || DEFAULT_VOICE_LOG
  const deepWaitMs = opts.deepWaitMs ?? 8000 // a non-streaming caller (a Siri Shortcut) waits this long for the deep brain
  const deepStreamMaxMs = opts.deepStreamMaxMs ?? 120000

  async function runTurn({ text, endpoint, sttMs, stream, emit }) {
    const t0 = performance.now()
    const turnId = randomUUID()
    const device = endpoint.name
    const canShow = endpoint.abilities.includes('show')
    const marks = { routing: null, firstToken: null, firstSentence: null }

    // What is spoken, as it is said. The holding line doesn't count toward the cap.
    const spoken = []
    let spokenChars = 0
    let truncated = false
    let closed = false
    const say = (sentence, extra = {}) => {
      if (closed || !sentence) return
      if (!extra.holding) {
        if (truncated) return
        const count = spoken.filter((s) => !s.holding).length
        if (count >= SPOKEN_CAP.maxSentences || spokenChars + sentence.length > SPOKEN_CAP.maxChars) {
          truncated = true
          sentence = SAY.restOnPhone
          extra = { ...extra, rest: true }
        } else {
          spokenChars += sentence.length + 1
        }
      }
      if (marks.firstSentence == null) marks.firstSentence = performance.now()
      spoken.push({ text: sentence, ...extra })
      emit({ type: 'sentence', text: sentence, ...extra })
    }

    const history = threadStore.page({ limit: 6 }).reverse()
    threadStore.append({ source: 'voice', role: 'user', text, meta: { device, turnId } })

    const route = await chooseBrain(text, { classify })
    marks.routing = performance.now()

    const finish = (result) => {
      const record = {
        turnId, ts: new Date().toISOString(), device, brain: result.brain,
        sttMs: Number.isFinite(sttMs) ? sttMs : null,
        routingMs: ms(t0, marks.routing),
        firstTokenMs: ms(t0, marks.firstToken),
        firstSentenceMs: ms(t0, marks.firstSentence),
        totalMs: ms(t0, performance.now()),
        truncated, ok: result.ok !== false
      }
      writeLog(logPath, record)
      return record
    }

    // ── a side effect: the plan, and the phone confirms ─────────────────────────────────────────────────────────
    if (route.kind === 'action') {
      const plan = planFor(text)
      const action = pendingActionStore.create({
        toolName: VOICE_REQUEST_TOOL,
        toolInput: { text, device, turnId },
        summary: `By voice from the ${device}: "${text}"`,
        sessionId: null
      })
      emit({ type: 'turn', turnId, brain: 'action' })
      say(plan)
      emit({ type: 'pending', actionId: action.id, summary: action.summary })
      threadStore.append({ source: 'voice', role: 'assistant', text: plan, meta: { device, turnId, brain: 'action', pendingActionId: action.id } })
      const timings = finish({ brain: 'action' })
      return { turnId, brain: 'action', speech: plan, pendingActionId: action.id, timings }
    }

    // ── the fast brain ──────────────────────────────────────────────────────────────────────────────────────────
    let fastDown = false
    if (route.kind === 'fast') {
      const sentences = createSentenceStream()
      let raw = ''
      let decided = false
      let escalate = false
      try {
        for await (const token of fastBrain({ text, history })) {
          if (marks.firstToken == null) marks.firstToken = performance.now()
          raw += token
          if (!decided) {
            if (raw.trim().length <= ESCALATE.length) continue // "deep" or "deeply"? wait for one more character
            decided = true
            if (isEscalation(raw)) { escalate = true; break }
            emit({ type: 'turn', turnId, brain: 'fast' })
            for (const s of sentences.push(raw)) say(s)
          } else {
            for (const s of sentences.push(token)) say(s)
          }
        }
        if (!decided) {
          if (!raw.trim() || isEscalation(raw)) escalate = true
          else { emit({ type: 'turn', turnId, brain: 'fast' }); for (const s of sentences.push(raw)) say(s) }
        }
      } catch (err) {
        console.error(`voice: fast brain failed: ${err.message}`)
        fastDown = true
        if (!spoken.length) escalate = true
      }
      if (!escalate) {
        for (const s of sentences.flush()) say(s)
        const display = toSpeakable(raw) || spoken.map((s) => s.text).join(' ')
        const speech = spoken.map((s) => s.text).join(' ')
        threadStore.append({ source: 'voice', role: 'assistant', text: display, meta: { device, turnId, brain: 'fast' } })
        const timings = finish({ brain: 'fast' })
        return { turnId, brain: 'fast', speech, ...(truncated && canShow ? { display } : {}), timings }
      }
      marks.firstToken = null // the deep brain's first token is the one that counts now
    }

    // ── the deep brain: the MARVIN session in the Thread, read-only from voice ──────────────────────────────────
    emit({ type: 'turn', turnId, brain: 'deep' })
    const holding = HOLDING[route.intent] || 'Checking.'
    if (stream) say(holding, { holding: true })

    const deep = (async () => {
      const sentences = createSentenceStream()
      const gate = createBannerGate()
      let accumulated = ''
      let resultText = ''
      let resultSessionId = null
      let failed = false
      const pendingSummary = threadStore.getState().pendingSummary
      // The framing goes first: it starts with "[", so the prompt can never be read as a CLI flag.
      const message = `${voiceFraming(device)}\n\n${pendingSummary ? `${pendingSummary}\n\n` : ''}${text}`
      try {
        for await (const evt of runSessionFn({ message, sessionId: threadStore.currentSession(), readOnly: true })) {
          if (evt.type === 'text' && evt.text) {
            const piece = gate(evt.text)
            if (!piece) continue
            if (marks.firstToken == null) marks.firstToken = performance.now()
            accumulated += piece
            for (const s of sentences.push(piece)) say(s)
          } else if (evt.type === 'result') {
            resultSessionId = evt.sessionId || resultSessionId
            resultText = stripBanner(evt.text)
            if (evt.isError) failed = true
          } else if (evt.type === 'session') {
            resultSessionId = resultSessionId || evt.sessionId
          } else if (evt.type === 'error') {
            failed = true
            console.error(`voice: deep brain error: ${evt.message}`)
          }
        }
      } catch (err) {
        failed = true
        console.error(`voice: deep brain threw: ${err.message}`)
      }
      for (const s of sentences.flush()) say(s)

      const display = (resultText || accumulated).trim()
      const ok = !!display && !(failed && !display)
      const reply = ok ? display : fastDown ? SAY.bothDown : SAY.deepFailed
      if (!ok) say(reply)
      if (ok && resultSessionId) {
        threadStore.setCurrentSession(resultSessionId)
        if (pendingSummary) threadStore.consumePendingSummary()
      }
      threadStore.append({
        source: 'voice', role: 'assistant', text: reply,
        sessionId: ok ? resultSessionId : null, meta: { device, turnId, brain: 'deep' }
      })
      return { ok, reply, timings: finish({ brain: 'deep', ok }) }
    })()

    const waitMs = stream ? deepStreamMaxMs : deepWaitMs
    let timer
    const outcome = await Promise.race([
      deep,
      new Promise((resolve) => { timer = setTimeout(() => resolve(null), waitMs) })
    ])
    clearTimeout(timer)

    if (!outcome) {
      // Still working: say so, and let the answer land in the Thread when it's ready.
      say(stream ? `This is taking a while. ${SAY.restOnPhone}` : `${holding} ${SAY.restOnPhone}`, { holding: true })
      closed = true
      deep.catch(() => {})
      return {
        turnId, brain: 'deep', deepPending: true,
        speech: spoken.map((s) => s.text).join(' '),
        timings: { routingMs: ms(t0, marks.routing), firstSentenceMs: ms(t0, marks.firstSentence) }
      }
    }
    closed = true
    const capped = outcome.ok ? capSpoken(outcome.reply, SPOKEN_CAP) : { speech: outcome.reply, truncated: false }
    return {
      turnId, brain: 'deep',
      speech: stream ? spoken.map((s) => s.text).join(' ') : capped.speech,
      ...((capped.truncated || truncated) && canShow ? { display: outcome.reply } : {}),
      timings: outcome.timings
    }
  }

  return async (req, res) => {
    const pathname = new URL(req.url, `http://${req.headers.host || 'localhost'}`).pathname
    if (req.method !== 'POST' || (pathname !== '/voice' && pathname !== '/voice/timing')) return false

    const { body, tooLarge } = await readBody(req)
    if (tooLarge) return sendJson(res, 413, { ok: false, error: 'body too large', speech: SAY.tooLong })
    let payload
    try {
      payload = JSON.parse(body)
      if (!payload || typeof payload !== 'object') throw new Error('not an object')
    } catch {
      return sendJson(res, 400, { ok: false, error: 'Invalid JSON', speech: SAY.garbled })
    }

    if (pathname === '/voice/timing') {
      const { turnId, firstSoundMs } = payload
      if (typeof turnId !== 'string' || !turnId || typeof firstSoundMs !== 'number' || !Number.isFinite(firstSoundMs) || firstSoundMs < 0) {
        return sendJson(res, 400, { ok: false, error: 'turnId (string) and firstSoundMs (number >= 0) are required' })
      }
      writeLog(logPath, { turnId, ts: new Date().toISOString(), firstSoundMs: Math.round(firstSoundMs) })
      return sendJson(res, 200, { ok: true })
    }

    const endpoint = resolveEndpoint(getEndpoints(), payload.source, payload.abilities)
    if (!endpoint) return sendJson(res, 403, { ok: false, error: `unknown device: ${String(payload.source ?? '(none)').slice(0, 40)}`, speech: SAY.unknownDevice })

    const text = typeof payload.text === 'string' ? payload.text.trim() : ''
    if (!text) return sendJson(res, 400, { ok: false, error: 'empty input', speech: SAY.empty })
    if (text.length > MAX_TEXT_CHARS) return sendJson(res, 413, { ok: false, error: 'text too long', speech: SAY.tooLong })

    const stream = payload.stream === true
    const sttMs = typeof payload.sttMs === 'number' ? payload.sttMs : null
    if (stream) res.writeHead(200, { 'Content-Type': 'application/x-ndjson', 'Transfer-Encoding': 'chunked' })
    const emit = stream ? (evt) => { try { res.write(JSON.stringify(evt) + '\n') } catch { /* client gone */ } } : () => {}

    try {
      const result = await runTurn({ text, endpoint, sttMs, stream, emit })
      if (stream) {
        emit({ type: 'done', ...result })
        res.end()
        return true
      }
      return sendJson(res, 200, { ok: true, data: result })
    } catch (err) {
      console.error(`voice: turn failed: ${err.stack || err.message}`)
      if (stream) {
        emit({ type: 'sentence', text: SAY.internal })
        emit({ type: 'done', speech: SAY.internal, ok: false })
        res.end()
        return true
      }
      return sendJson(res, 500, { ok: false, error: err.message, speech: SAY.internal })
    }
  }
}

// When the phone resolves a voice request (Face ID, then allow or deny), run it as a full Thread turn or record the
// cancellation. Other pending actions (the tool-permission hook's) are not ours and are left alone.
export function createVoiceApprovalHandler(opts = {}) {
  const threadStore = opts.threadStore
  const runSessionFn = opts.runSession || runSession
  const maxAgeMs = opts.maxAgeMs ?? 15 * 60 * 1000
  const now = opts.now || Date.now

  return async (action) => {
    if (!action || action.toolName !== VOICE_REQUEST_TOOL || action.status === 'pending') return
    const { text, device, turnId } = action.toolInput || {}
    const meta = { device, turnId, confirmedActionId: action.id }

    if (action.decision !== 'allow') {
      threadStore.append({ source: 'voice', role: 'assistant', text: `Cancelled on the phone: "${text}".`, meta })
      return
    }
    if (now() - action.createdAt > maxAgeMs) {
      threadStore.append({ source: 'voice', role: 'assistant', text: `Not done: that request expired before it was confirmed ("${text}"). Ask again.`, meta })
      return
    }

    const message = [
      `Confirmed on the phone with Face ID. Earlier, by voice from the ${device}, ${ownerName() || 'the owner'} asked: "${text}".`,
      'Do it now, then say in one or two sentences what you did.'
    ].join(' ')
    let accumulated = ''
    let resultText = ''
    let sessionId = null
    let failed = false
    try {
      for await (const evt of runSessionFn({ message, sessionId: threadStore.currentSession() })) {
        if (evt.type === 'text' && evt.text) accumulated += stripBanner(evt.text)
        else if (evt.type === 'result') { sessionId = evt.sessionId || sessionId; resultText = stripBanner(evt.text); if (evt.isError) failed = true }
        else if (evt.type === 'error') failed = true
      }
    } catch (err) {
      failed = true
      console.error(`voice: confirmed request failed: ${err.message}`)
    }
    const reply = (resultText || accumulated).trim()
    if (reply && sessionId) threadStore.setCurrentSession(sessionId)
    threadStore.append({
      source: 'voice', role: 'assistant',
      text: reply || (failed ? `The confirmed request failed: "${text}". Nothing may have been done; check before retrying.` : 'Done.'),
      sessionId: reply ? sessionId : null, meta
    })
  }
}

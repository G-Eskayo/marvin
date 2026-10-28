import { runSession } from './session_runner.js'
import { shouldRotate, summarize } from './rotation_policy.js'
import { classifyBrain } from './brain_router.js'
import { createSentenceStreamer, toSpeakable } from './speakable.js'
import { isKnownDevice } from './voice_devices.js'

export function createVoiceApiRouter(opts = {}) {
  const runSessionFn = opts.runSession || runSession
  const threadStore = opts.threadStore
  const permissionHookPath = opts.permissionHookPath

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /voice with { text, device }
      if (req.method === 'POST' && pathname === '/voice') {
        // Read body as JSON
        let body = ''
        for await (const chunk of req) {
          body += chunk.toString()
        }

        let payload
        try {
          payload = JSON.parse(body)
        } catch {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid JSON' })
          )
          return true
        }

        const { text, device } = payload

        // Validate text
        if (!text || typeof text !== 'string') {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid text field' })
          )
          return true
        }

        // Validate device
        if (!device || !isKnownDevice(device)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid device field' })
          )
          return true
        }

        // Stream events back as newline-delimited JSON
        res.writeHead(200, {
          'Content-Type': 'application/x-ndjson',
          'Transfer-Encoding': 'chunked'
        })

        try {
          const routingStartTime = Date.now()

          // Classify the brain intent
          const classification = await classifyBrain(text)
          const routingMs = Date.now() - routingStartTime

          // Get current session and pending summary
          const currentSessionId = threadStore.currentSession()
          const pendingSummary = threadStore.getState().pendingSummary

          // Construct the outgoing message
          let outgoingMessage = text
          if (pendingSummary) {
            outgoingMessage = `${pendingSummary}\n\n${text}`
          }

          // Append user message to thread store
          const userMessageId = threadStore.append({
            source: 'voice',
            role: 'user',
            text: text
          }).id

          let resultSessionId = null
          let assistantText = ''
          let firstTokenTime = null
          let firstSentenceTime = null
          let firstReplyTime = null
          let hasEmittedPlaceholder = false

          const sentenceStreamer = createSentenceStreamer()

          // Emit classification event
          res.write(JSON.stringify({
            type: 'classification',
            intent: classification.intent,
            brainType: classification.brainType,
            method: classification.method,
            score: classification.score,
            routingMs
          }) + '\n')

          // Emit placeholder before running session (for deep brain)
          if (classification.brainType === 'deep') {
            res.write(JSON.stringify({
              type: 'placeholder',
              text: 'Thinking...'
            }) + '\n')
            hasEmittedPlaceholder = true
            firstReplyTime = Date.now()
          }

          const sessionStartTime = Date.now()

          for await (const event of runSessionFn({
            message: outgoingMessage,
            sessionId: currentSessionId,
            permissionHookPath
          })) {
            // Capture the final sessionId from result events
            if (event.type === 'result' && event.sessionId) {
              resultSessionId = event.sessionId
            }

            // Track timing for first text
            if (event.type === 'text' && !firstTokenTime) {
              firstTokenTime = Date.now() - sessionStartTime
              if (!firstReplyTime) {
                firstReplyTime = Date.now()
              }
            }

            // Accumulate assistant text
            if (event.type === 'text') {
              assistantText += event.text

              // Stream speakable sentences
              const sentences = sentenceStreamer.push(event.text)
              for (const sentence of sentences) {
                const speakable = toSpeakable(sentence)
                if (speakable && !firstSentenceTime) {
                  firstSentenceTime = Date.now()
                }
                res.write(JSON.stringify({
                  type: 'sentence',
                  text: speakable
                }) + '\n')
              }
            }

            // Emit error events as spoken fallback
            if (event.type === 'error') {
              const fallback = `I encountered an error: ${event.message}`
              res.write(JSON.stringify({
                type: 'error_speech',
                text: fallback
              }) + '\n')
            }
          }

          // Finish sentence streaming for any remaining text
          const remainingSentences = sentenceStreamer.finish()
          for (const sentence of remainingSentences) {
            const speakable = toSpeakable(sentence)
            if (speakable && !firstSentenceTime) {
              firstSentenceTime = Date.now()
            }
            res.write(JSON.stringify({
              type: 'sentence',
              text: speakable
            }) + '\n')
          }

          // Backfill user message sessionId and append assistant message
          if (resultSessionId) {
            threadStore.backfillSession(userMessageId, resultSessionId)

            // Append assistant message
            threadStore.append({
              source: 'voice',
              role: 'assistant',
              text: assistantText,
              sessionId: resultSessionId
            })

            // Set current session
            threadStore.setCurrentSession(resultSessionId)

            // Consume pending summary if present
            threadStore.consumePendingSummary()

            // Check for rotation
            const sessionState = threadStore.getState()
            const sessionMessages = sessionState.messages.filter(m => m.sessionId === resultSessionId)

            const rotationResult = shouldRotate({
              sessionMessages,
              newMessageText: text,
              lengthThreshold: 10,
              topicShiftFn: () => {
                return { shift: false }
              }
            })

            if (rotationResult.rotate) {
              const summary = summarize(sessionMessages, { maxLen: 500 })
              threadStore.rotate({
                summary,
                fromSessionId: resultSessionId
              })
            }
          }

          // Emit timing information
          const totalTime = Date.now() - routingStartTime
          res.write(JSON.stringify({
            type: 'timing',
            routingMs,
            firstTokenMs: firstTokenTime,
            firstSentenceMs: firstSentenceTime ? firstSentenceTime - routingStartTime : null,
            firstReplyMs: firstReplyTime ? firstReplyTime - routingStartTime : null,
            totalMs: totalTime
          }) + '\n')
        } catch (err) {
          res.write(JSON.stringify({
            type: 'error',
            message: err.message
          }) + '\n')
        }

        res.end()
        return true
      }

      // No route matched
      return false
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: false, error: err.message })
      )
      return true
    }
  }
}

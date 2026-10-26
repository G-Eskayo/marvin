import { runSession } from './session_runner.js'
import { toSpeakable } from './speakable.js'
import { isKnownDevice } from './device_abilities.js'

// Default brain selection: research/recall intents use fast (Ollama), others use deep (Claude)
const INTENT_TO_BRAIN = {
  research: 'fast',
  recall: 'fast',
  coding: 'deep',
  architecture: 'deep'
}

const MAX_TEXT_LENGTH = 4000

export function createVoiceApiRouter(opts = {}) {
  const threadStore = opts.threadStore
  const routeClassify = opts.routeClassify || (async (text) => 'architecture') // default to deep
  const fastBrain = opts.fastBrain
  const deepBrain = opts.deepBrain || runSession
  const cannedResponse = opts.cannedResponse
  const permissionHookPath = opts.permissionHookPath

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /voice with { from, text }
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

        const { from, text } = payload

        // Defect 7: Validate `from` field and text length
        if (!from || typeof from !== 'string' || !isKnownDevice(from)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid from field (unknown device)' })
          )
          return true
        }

        if (!text || typeof text !== 'string') {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid text field' })
          )
          return true
        }

        if (text.length > MAX_TEXT_LENGTH) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: `Text exceeds maximum length of ${MAX_TEXT_LENGTH}` })
          )
          return true
        }

        // Stream events back as newline-delimited JSON
        res.writeHead(200, {
          'Content-Type': 'application/x-ndjson',
          'Transfer-Encoding': 'chunked'
        })

        try {
          let intent = 'architecture'
          let brainChoice = 'deep'

          // Defect 4: Handle routing failure — fall back to deep brain
          try {
            intent = await routeClassify(text)
            brainChoice = INTENT_TO_BRAIN[intent] || 'deep'
          } catch (routeError) {
            // Log routing error but fall back to deep brain
            console.error(`Voice routing error: ${routeError.message}; falling back to deep brain`)
            intent = 'architecture'
            brainChoice = 'deep'
          }

          // Append user message to thread store
          const userMessageId = threadStore.append({
            source: 'voice',
            role: 'user',
            text: text,
            from: from
          }).id

          let assistantText = ''
          let sessionId = null

          // Select and call the appropriate brain
          let brain
          if (brainChoice === 'fast' && fastBrain) {
            brain = fastBrain
          } else {
            brain = deepBrain
          }

          try {
            for await (const event of brain({
              message: text,
              sessionId,
              permissionHookPath
            })) {
              // Capture session ID from session events
              if (event.type === 'session' && event.sessionId) {
                sessionId = event.sessionId
              }

              // Accumulate assistant text
              if (event.type === 'text') {
                assistantText += event.text
              }

              // Defect 3: Apply toSpeakable to streamed text events before sending to client
              let eventToSend = event
              if (event.type === 'text') {
                eventToSend = {
                  ...event,
                  text: toSpeakable(event.text)
                }
              }

              // Stream the event back to the client
              res.write(JSON.stringify(eventToSend) + '\n')
            }
          } catch (brainError) {
            // On error, attempt fallback to canned response
            res.write(JSON.stringify({
              type: 'error',
              message: `Brain error: ${brainError.message}. Using fallback response.`
            }) + '\n')

            if (cannedResponse) {
              for await (const event of cannedResponse()) {
                if (event.type === 'text') {
                  assistantText += event.text
                }
                // Defect 3: Apply toSpeakable to canned response text too
                let eventToSend = event
                if (event.type === 'text') {
                  eventToSend = {
                    ...event,
                    text: toSpeakable(event.text)
                  }
                }
                res.write(JSON.stringify(eventToSend) + '\n')
              }
            }
          }

          // Defect 5: Ensure assistant message is never empty
          if (!assistantText && cannedResponse) {
            // If we still have no text, try the canned response one more time
            for await (const event of cannedResponse()) {
              if (event.type === 'text') {
                assistantText += event.text
              }
            }
          }

          // If still empty, use a fallback message
          const finalAssistantText = assistantText || 'I encountered an error processing your request.'

          // Apply toSpeakable one more time to the final accumulated response
          const speakableText = toSpeakable(finalAssistantText)

          // Append assistant message
          threadStore.append({
            source: 'voice',
            role: 'assistant',
            text: speakableText,
            sessionId: sessionId,
            from: from
          })

          // Defect 6: Don't overwrite the chat interface's current session
          // Voice turns use their own session context; don't interfere with chat
          // (voice session would be sessionId if we need to track it separately)
        } catch (err) {
          res.write(JSON.stringify({
            type: 'error',
            message: err.message
          }) + '\n')
        }

        res.end()
        return true
      }

      // GET /thread?limit=<n>&before=<id>
      if (req.method === 'GET' && pathname === '/thread') {
        const limit = parseInt(url.searchParams.get('limit')) || 50
        const before = url.searchParams.get('before') || null

        try {
          const messages = threadStore.page({ limit, before })
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: messages })
          )
        } catch (err) {
          res.writeHead(500, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: err.message })
          )
        }

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

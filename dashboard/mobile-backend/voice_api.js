import { toSpeakable } from './to_speakable.js'
import { createSentenceStream } from './sentence_stream.js'
import { logStage } from './voice_latency.js'
import { runSession } from './session_runner.js'
import { shouldRotate, summarize } from './rotation_policy.js'

const VALID_DEVICES = ['homepod', 'mac', 'iphone', 'watch']
const MAX_TEXT_LENGTH = 10000

export function createVoiceApiRouter(opts = {}) {
  const threadStore = opts.threadStore
  const runSessionFn = opts.runSession || runSession
  const callFastBrainFn = opts.callFastBrain
  const chooseBrainFn = opts.chooseBrain
  const logStageFn = opts.logStage || logStage
  const permissionHookPath = opts.permissionHookPath

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /voice with { text, device, abilities?, clientId?, stream? }
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

        const { text, device, abilities, clientId, stream } = payload
        const streamEnabled = stream !== false // Default true

        // Validate text
        if (!text || typeof text !== 'string' || text.trim().length === 0) {
          res.writeHead(422, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid text field' })
          )
          return true
        }

        if (text.length > MAX_TEXT_LENGTH) {
          res.writeHead(422, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: `Text exceeds maximum length of ${MAX_TEXT_LENGTH}` })
          )
          return true
        }

        // Validate device (case-insensitive)
        if (!device || typeof device !== 'string' || !VALID_DEVICES.includes(device.toLowerCase())) {
          res.writeHead(422, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid or missing device field. Valid: homepod, mac, iphone, watch' })
          )
          return true
        }

        const turnId = clientId || `turn-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
        const receivedTs = Date.now()

        try {
          // Log received stage (best-effort, don't block on failure)
          logStageFn(turnId, 'received', receivedTs, {}).catch(() => {})

          // Check for dedup by clientId
          if (clientId && threadStore.findByClientId(clientId)) {
            res.writeHead(200, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: true, turnId, deduped: true })
            )
            return true
          }

          // Append user message
          const userMessageId = threadStore.append({
            source: 'voice',
            role: 'user',
            text: text.trim(),
            clientId,
            device: device.toLowerCase()
          }).id

          const routedTs = Date.now()
          logStageFn(turnId, 'routed', routedTs, {}).catch(() => {})

          // Choose brain
          const brainChoice = await chooseBrainFn(text, { abilities })

          // Set up response streaming
          res.writeHead(200, {
            'Content-Type': 'application/x-ndjson',
            'Transfer-Encoding': 'chunked'
          })

          res.write(JSON.stringify({
            type: 'metadata',
            turnId,
            brain: brainChoice.type,
            stream: streamEnabled
          }) + '\n')

          let assistantText = ''
          let allText = ''
          const sentenceStream = createSentenceStream()
          let firstTokenLogged = false
          let firstSentenceLogged = false

          try {
            if (brainChoice.type === 'deep') {
              // Deep brain path: use Claude
              const currentSessionId = threadStore.currentSession()
              const pendingSummary = threadStore.getState?.()?.pendingSummary
              let outgoingMessage = text
              if (pendingSummary) {
                outgoingMessage = `${pendingSummary}\n\n${text}`
              }

              let resultSessionId = null
              let errorOccurred = false
              let rawDeltaBuffer = ''

              for await (const event of runSessionFn({
                message: outgoingMessage,
                sessionId: currentSessionId,
                permissionHookPath
              })) {
                if (event.type === 'result' && event.sessionId) {
                  resultSessionId = event.sessionId
                }

                if (event.type === 'error') {
                  errorOccurred = true
                  const fallback = 'I encountered an error. Please try again.'
                  res.write(JSON.stringify({
                    type: 'error',
                    message: event.message || 'Unknown error'
                  }) + '\n')
                  res.write(JSON.stringify({
                    type: 'sentence',
                    text: fallback
                  }) + '\n')
                  assistantText = fallback
                  break
                }

                if (event.type === 'text') {
                  allText += event.text
                  rawDeltaBuffer += event.text

                  // Log first token
                  if (!firstTokenLogged && allText.length > 0) {
                    firstTokenLogged = true
                    const firstTokenTs = Date.now()
                    logStageFn(turnId, 'first_token', firstTokenTs, {}).catch(() => {})
                  }

                  // Process accumulated raw text through sentence stream
                  const sentences = sentenceStream.push(rawDeltaBuffer)
                  rawDeltaBuffer = ''

                  for (const rawSentence of sentences) {
                    // Apply speakable transformation to complete sentences
                    const speakable = toSpeakable(rawSentence)
                    if (speakable) {
                      // Log first sentence
                      if (!firstSentenceLogged) {
                        firstSentenceLogged = true
                        const firstSentenceTs = Date.now()
                        logStageFn(turnId, 'first_sentence', firstSentenceTs, {}).catch(() => {})
                      }

                      assistantText += speakable + ' '
                      res.write(JSON.stringify({
                        type: 'sentence',
                        text: speakable
                      }) + '\n')
                    }
                  }
                }

                // Emit raw events too (but not text or result)
                if (event.type !== 'text' && event.type !== 'result' && event.type !== 'error') {
                  res.write(JSON.stringify(event) + '\n')
                }
              }

              if (!errorOccurred) {
                // Flush remaining fragment with speakable transformation
                const fragment = sentenceStream.flush()
                if (fragment) {
                  const speakable = toSpeakable(fragment)
                  if (speakable) {
                    if (!firstSentenceLogged) {
                      firstSentenceLogged = true
                      const firstSentenceTs = Date.now()
                      logStageFn(turnId, 'first_sentence', firstSentenceTs, {}).catch(() => {})
                    }
                    assistantText += speakable
                    res.write(JSON.stringify({
                      type: 'sentence',
                      text: speakable
                    }) + '\n')
                  }
                }

                // Backfill and append to store (if we got a valid session)
                if (resultSessionId) {
                  threadStore.backfillSession(userMessageId, resultSessionId)
                  threadStore.append({
                    source: 'voice',
                    role: 'assistant',
                    text: assistantText.trim(),
                    sessionId: resultSessionId
                  })
                  threadStore.setCurrentSession(resultSessionId)

                  // Consume pending summary if present
                  if (threadStore.consumePendingSummary) {
                    threadStore.consumePendingSummary()
                  }

                  // Check for rotation
                  const sessionState = threadStore.getState?.()
                  if (sessionState) {
                    const sessionMessages = sessionState.messages?.filter(m => m.sessionId === resultSessionId) || []
                    const rotationResult = shouldRotate({
                      sessionMessages,
                      newMessageText: text,
                      lengthThreshold: 10,
                      topicShiftFn: () => ({ shift: false })
                    })

                    if (rotationResult.rotate) {
                      const summary = summarize(sessionMessages, { maxLen: 500 })
                      threadStore.rotate({
                        summary,
                        fromSessionId: resultSessionId
                      })
                    }
                  }
                } else {
                  // No valid session ID - treat as error
                  const fallback = 'The service is temporarily unavailable. Please try again in a moment.'
                  res.write(JSON.stringify({
                    type: 'error',
                    fallback
                  }) + '\n')
                  res.write(JSON.stringify({
                    type: 'sentence',
                    text: fallback
                  }) + '\n')
                  threadStore.append({
                    source: 'voice',
                    role: 'assistant',
                    text: fallback
                  })
                }
              } else if (errorOccurred) {
                // On error, still append the fallback message
                threadStore.append({
                  source: 'voice',
                  role: 'assistant',
                  text: assistantText
                })
              }
            } else if (brainChoice.type === 'fast') {
              // Fast brain path: use Ollama
              let rawDeltaBuffer = ''
              let fastBrainError = false

              try {
                const result = await callFastBrainFn({
                  text,
                  stream: streamEnabled,
                  onChunk: (chunk) => {
                    if (!chunk) return

                    allText += chunk
                    rawDeltaBuffer += chunk

                    // Log first token
                    if (!firstTokenLogged && allText.length > 0) {
                      firstTokenLogged = true
                      const firstTokenTs = Date.now()
                      logStageFn(turnId, 'first_token', firstTokenTs, {}).catch(() => {})
                    }

                    // Process accumulated raw text through sentence stream
                    const sentences = sentenceStream.push(rawDeltaBuffer)
                    rawDeltaBuffer = ''

                    for (const rawSentence of sentences) {
                      // Apply speakable transformation to complete sentences
                      const speakable = toSpeakable(rawSentence)
                      if (speakable) {
                        // Log first sentence
                        if (!firstSentenceLogged) {
                          firstSentenceLogged = true
                          const firstSentenceTs = Date.now()
                          logStageFn(turnId, 'first_sentence', firstSentenceTs, {}).catch(() => {})
                        }

                        assistantText += speakable + ' '
                        res.write(JSON.stringify({
                          type: 'sentence',
                          text: speakable
                        }) + '\n')
                      }
                    }
                  }
                })

                // For non-streaming mode, capture the returned text
                if (!streamEnabled && result) {
                  allText += result
                  rawDeltaBuffer += result

                  if (!firstTokenLogged && result.length > 0) {
                    firstTokenLogged = true
                    const firstTokenTs = Date.now()
                    logStageFn(turnId, 'first_token', firstTokenTs, {}).catch(() => {})
                  }

                  // Process through sentence stream
                  const sentences = sentenceStream.push(rawDeltaBuffer)
                  rawDeltaBuffer = ''

                  for (const rawSentence of sentences) {
                    const speakable = toSpeakable(rawSentence)
                    if (speakable) {
                      if (!firstSentenceLogged) {
                        firstSentenceLogged = true
                        const firstSentenceTs = Date.now()
                        logStageFn(turnId, 'first_sentence', firstSentenceTs, {}).catch(() => {})
                      }

                      assistantText += speakable + ' '
                      res.write(JSON.stringify({
                        type: 'sentence',
                        text: speakable
                      }) + '\n')
                    }
                  }
                }
              } catch (err) {
                fastBrainError = true
                // Fallback: emit a spoken fallback sentence
                const fallback = 'I encountered an error. Please try again.'
                res.write(JSON.stringify({
                  type: 'error',
                  message: err.message
                }) + '\n')
                res.write(JSON.stringify({
                  type: 'sentence',
                  text: fallback
                }) + '\n')
                assistantText = fallback
              }

              if (!fastBrainError) {
                // Flush remaining fragment with speakable transformation
                const fragment = sentenceStream.flush()
                if (fragment) {
                  const speakable = toSpeakable(fragment)
                  if (speakable) {
                    if (!firstSentenceLogged) {
                      firstSentenceLogged = true
                      const firstSentenceTs = Date.now()
                      logStageFn(turnId, 'first_sentence', firstSentenceTs, {}).catch(() => {})
                    }
                    assistantText += speakable
                    res.write(JSON.stringify({
                      type: 'sentence',
                      text: speakable
                    }) + '\n')
                  }
                }
              }

              // Append to store
              threadStore.append({
                source: 'voice',
                role: 'assistant',
                text: assistantText.trim()
              })
            }
          } catch (err) {
            // Brain unreachable fallback
            const fallback = 'The service is temporarily unavailable. Please try again in a moment.'
            res.write(JSON.stringify({
              type: 'error',
              message: err.message,
              fallback
            }) + '\n')

            // Still append the fallback message
            threadStore.append({
              source: 'voice',
              role: 'assistant',
              text: fallback
            })
          }

          res.end()
          return true
        } catch (err) {
          res.write(JSON.stringify({
            type: 'error',
            message: err.message
          }) + '\n')
          res.end()
          return true
        }
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

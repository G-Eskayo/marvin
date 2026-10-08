// Process a batch of offline exchanges, deduplicating by clientId,
// appending new ones to thread store, and running a one-shot review session.
// Reference: ADR 0045 (offline model) and ADR 0003 (memory boundary).
export async function processOfflineBatch({ exchanges, threadStore, runSessionFn }) {
  const result = {
    ok: true,
    appended: 0,
    skipped: 0,
    reviewed: false,
    sessionId: null,
    error: null
  }

  // Filter out exchanges whose clientId already exists (idempotent re-send)
  const newExchanges = []
  for (const exchange of exchanges) {
    if (threadStore.hasClientId(exchange.clientId)) {
      result.skipped++
    } else {
      newExchanges.push(exchange)
    }
  }

  // Append new exchanges to thread store with source='offline'
  const messageIds = []
  for (const exchange of newExchanges) {
    const message = threadStore.append({
      source: 'offline',
      role: exchange.role,
      text: exchange.text,
      clientId: exchange.clientId,
      sessionId: null,
      ts: exchange.ts
    })
    messageIds.push(message.id)
    result.appended++
  }

  // If there's at least one newly-appended exchange, run a review session
  if (newExchanges.length > 0) {
    try {
      // Construct a batch prompt for the review session
      const batchText = newExchanges
        .map(ex => `[${ex.role}]: ${ex.text}`)
        .join('\n')

      const prompt = `Review these offline messages and decide what's worth saving to memory:\n\n${batchText}`

      // Run a one-shot review session (no --resume, fresh session)
      let reviewSessionId = null
      for await (const event of runSessionFn({ message: prompt })) {
        if (event.type === 'result' && event.sessionId) {
          reviewSessionId = event.sessionId
        }
        if (event.type === 'error') {
          result.error = event.message
          // Don't throw — messages are already persisted, just report the error
          return result
        }
      }

      // Backfill the sessionId onto each newly-appended message
      if (reviewSessionId) {
        for (const messageId of messageIds) {
          threadStore.backfillSession(messageId, reviewSessionId)
        }
        result.sessionId = reviewSessionId
        result.reviewed = true
      }
    } catch (err) {
      result.error = err.message
      // Messages are already persisted, just report the error
      return result
    }
  }

  return result
}

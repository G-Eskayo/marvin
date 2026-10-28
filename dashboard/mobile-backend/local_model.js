// Stream text from a local model via Ollama's streaming HTTP API
export async function* streamLocalModel({ prompt, model, baseUrl, fetchFn } = {}) {
  const url = new URL('/api/generate', baseUrl || 'http://localhost:11434')
  const fetch = fetchFn || globalThis.fetch

  const payload = {
    model,
    prompt,
    stream: true
  }

  try {
    const response = await fetch(url.toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (!response.ok) {
      yield {
        type: 'error',
        message: `Ollama API error: ${response.status} ${response.statusText}`
      }
      return
    }

    // Read the response stream
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Process complete lines (newline-delimited JSON)
        const lines = buffer.split('\n')
        buffer = lines[lines.length - 1] // Keep incomplete line in buffer

        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i].trim()
          if (!line) continue

          try {
            const chunk = JSON.parse(line)
            if (chunk.response) {
              yield {
                type: 'text',
                text: chunk.response
              }
            }
            if (chunk.done) {
              // Final message
              yield {
                type: 'result',
                done: true
              }
            }
          } catch (e) {
            // Skip malformed JSON lines
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  } catch (err) {
    yield {
      type: 'error',
      message: `Failed to reach Ollama: ${err.message}`
    }
  }
}

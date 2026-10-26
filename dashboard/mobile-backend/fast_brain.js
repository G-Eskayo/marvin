import http from 'http'
import https from 'https'

// Default POST function that mirrors post_json.js pattern
function defaultPostFn(url, payload, opts = {}) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url)
    const body = JSON.stringify(payload)

    const options = {
      hostname: urlObj.hostname,
      port: urlObj.port,
      path: urlObj.pathname + urlObj.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      },
      timeout: opts.timeout || 30000 // 30 second default timeout
    }

    const transport = urlObj.protocol === 'https:' ? https : http
    const req = transport.request(options, (res) => {
      if (opts.stream) {
        // Streaming mode: caller expects to read chunks line by line
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, stream: res })
      } else {
        // Non-streaming: accumulate and parse JSON
        let data = ''
        res.on('data', (chunk) => { data += chunk })
        res.on('end', () => {
          const ok = res.statusCode >= 200 && res.statusCode < 300
          try {
            const json = JSON.parse(data)
            resolve({ ok, status: res.statusCode, json: async () => json })
          } catch {
            resolve({ ok, status: res.statusCode, json: async () => ({ error: data }) })
          }
        })
      }
    })

    req.on('error', reject)
    req.on('timeout', () => {
      req.destroy()
      reject(new Error('Request timeout'))
    })
    req.write(body)
    req.end()
  })
}

// POST to Ollama's /api/chat and handle response
export async function callFastBrain({ text, postFn, stream, onChunk } = {}) {
  const actualPostFn = postFn || defaultPostFn
  const ollamaUrl = process.env.OLLAMA_URL || 'http://localhost:11434'

  const payload = {
    model: 'qwen2.5:3b',
    messages: [
      {
        role: 'user',
        content: text
      }
    ],
    stream: !!stream
  }

  const url = `${ollamaUrl}/api/chat`

  if (stream && onChunk) {
    // Streaming mode: read newline-delimited JSON chunks
    const response = await actualPostFn(url, payload, { stream: true })

    if (!response.ok) {
      const error = await response.json()
      throw new Error(`Ollama error: ${response.status} - ${error.error || 'Unknown error'}`)
    }

    return new Promise((resolve, reject) => {
      let buffer = ''
      const stream = response.stream

      stream.on('data', (chunk) => {
        buffer += chunk.toString()
        const lines = buffer.split('\n')

        // Process complete lines (all but the last, which might be partial)
        for (let i = 0; i < lines.length - 1; i++) {
          try {
            const parsed = JSON.parse(lines[i])
            if (parsed.message && parsed.message.content) {
              onChunk(parsed.message.content)
            }
          } catch {
            // Skip malformed lines
          }
        }

        // Keep the last partial line in buffer
        buffer = lines[lines.length - 1]
      })

      stream.on('end', () => {
        // Process final partial line if any
        if (buffer.trim()) {
          try {
            const parsed = JSON.parse(buffer)
            if (parsed.message && parsed.message.content) {
              onChunk(parsed.message.content)
            }
          } catch {}
        }
        resolve()
      })

      stream.on('error', reject)
    })
  } else {
    // Non-streaming mode: get full response
    const response = await actualPostFn(url, payload, { stream: false, timeout: 30000 })

    if (!response.ok) {
      const error = await response.json()
      throw new Error(`Ollama error: ${response.status} - ${error.error || 'Unknown error'}`)
    }

    const data = await response.json()
    return data.message?.content || ''
  }
}

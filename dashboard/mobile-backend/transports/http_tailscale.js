import http from 'http'

export function createHttpTailscaleTransport(host, port = 7880) {
  const baseUrl = `http://${host}:${port}`
  let isConnected = false

  return {
    async connect() {
      isConnected = true
    },

    async disconnect() {
      isConnected = false
    },

    async ping() {
      if (!isConnected) {
        const err = new Error('Transport not connected')
        err.code = 'NOT_CONNECTED'
        throw err
      }

      return new Promise((resolve, reject) => {
        const url = new URL('/bench/ping', baseUrl)
        http.get(url, (res) => {
          if (res.statusCode >= 400) {
            reject(new Error(`ping failed with status ${res.statusCode}`))
            return
          }

          let data = ''
          res.on('data', chunk => { data += chunk })
          res.on('end', () => {
            try {
              const parsed = JSON.parse(data)
              if (parsed.ok) {
                resolve(parsed)
              } else {
                reject(new Error(parsed.error || 'ping failed'))
              }
            } catch (e) {
              reject(e)
            }
          })
        }).on('error', reject)
      })
    },

    async stream(opts = {}) {
      if (!isConnected) {
        const err = new Error('Transport not connected')
        err.code = 'NOT_CONNECTED'
        throw err
      }

      const chunks = opts.chunks || 10
      let totalBytes = 0
      let ttfbMs = null
      const sequence = []
      let buffer = ''

      return new Promise((resolve, reject) => {
        const url = new URL('/bench/stream', baseUrl)
        url.searchParams.set('chunks', chunks)

        const firstDataTime = Date.now()
        http.get(url, (res) => {
          if (res.statusCode >= 400) {
            reject(new Error(`stream failed with status ${res.statusCode}`))
            return
          }

          res.on('data', chunk => {
            if (ttfbMs === null) {
              ttfbMs = Date.now() - firstDataTime
            }

            totalBytes += chunk.length
            buffer += chunk.toString()

            const lines = buffer.split('\n')
            for (let i = 0; i < lines.length - 1; i++) {
              try {
                const parsed = JSON.parse(lines[i])
                if (typeof parsed.index === 'number') {
                  sequence.push({ seqn: parsed.index })
                }
              } catch (e) {
                // Ignore parse errors for partial lines
              }
            }
            buffer = lines[lines.length - 1]
          })

          res.on('end', () => {
            if (buffer.trim()) {
              try {
                const parsed = JSON.parse(buffer)
                if (typeof parsed.index === 'number') {
                  sequence.push({ seqn: parsed.index })
                }
              } catch (e) {
                // Ignore parse errors
              }
            }

            resolve({
              bytes: totalBytes,
              ttfbMs,
              sequence
            })
          })
        }).on('error', reject)
      })
    }
  }
}

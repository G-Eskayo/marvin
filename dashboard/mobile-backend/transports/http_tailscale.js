import http from 'http'
import { throughputMbps } from '../bench_client.js'
import { DEFAULT_TIMEOUT_MS } from '../bench_limits.js'

function createIdleTimeoutHelper(timeoutMs) {
  let timeoutHandle = null

  function resetTimeout(onTimeout) {
    if (timeoutHandle) clearTimeout(timeoutHandle)
    timeoutHandle = setTimeout(onTimeout, timeoutMs)
  }

  function clear() {
    if (timeoutHandle) clearTimeout(timeoutHandle)
  }

  return { resetTimeout, clear }
}

export function createHttpTailscaleTransport(baseUrl, opts = {}) {
  const url = new URL(baseUrl)
  const hostname = url.hostname
  const port = parseInt(url.port || '80', 10)
  const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS

  return {
    async connect() {
      return { connected: true }
    },

    async disconnect() {
      return { disconnected: true }
    },

    async ping() {
      const startMs = Date.now()
      const req = http.get({
        hostname,
        port,
        path: '/bench/ping',
        method: 'GET',
        timeout: timeoutMs
      })

      return new Promise((resolve, reject) => {
        const idleHelper = createIdleTimeoutHelper(timeoutMs)
        const onTimeout = () => {
          req.destroy()
          reject(new Error('ping timeout'))
        }

        idleHelper.resetTimeout(onTimeout)

        req.on('response', (res) => {
          idleHelper.clear()
          const ttfbMs = Date.now() - startMs
          if (res.statusCode >= 400) {
            res.resume()
            reject(new Error(`ping failed: ${res.statusCode}`))
            return
          }
          let body = ''
          res.on('data', (chunk) => {
            body += chunk.toString()
          })
          res.on('end', () => {
            resolve({ ttfbMs, statusCode: res.statusCode })
          })
        })
        req.on('error', (err) => {
          idleHelper.clear()
          reject(err)
        })
        req.end()
      })
    },

    async stream(chunkCount = 10) {
      const startMs = Date.now()
      let aborted = false
      let buffer = Buffer.alloc(0)
      const chunkSequence = []

      return new Promise((resolve, reject) => {
        const req = http.get({
          hostname,
          port,
          path: `/bench/stream?chunks=${chunkCount}`,
          method: 'GET',
          timeout: timeoutMs
        })

        let ttfbMs = null
        const idleHelper = createIdleTimeoutHelper(timeoutMs)
        const onTimeout = () => {
          aborted = true
          req.destroy()
          reject(new Error('stream timeout'))
        }

        idleHelper.resetTimeout(onTimeout)

        req.on('response', (res) => {
          idleHelper.clear()
          ttfbMs = Date.now() - startMs

          if (res.statusCode >= 400) {
            aborted = true
            res.resume()
            reject(new Error(`stream failed: ${res.statusCode}`))
            return
          }

          res.on('data', (chunk) => {
            if (!aborted) {
              buffer = Buffer.concat([buffer, chunk])

              while (buffer.length >= 1024) {
                const frame = buffer.subarray(0, 1024)
                const index = frame.readUInt16BE(0)
                chunkSequence.push(index)
                buffer = buffer.subarray(1024)
              }
            }
          })

          res.on('end', () => {
            idleHelper.clear()
            if (!aborted) {
              const totalBytes = (chunkSequence.length * 1024) + buffer.length
              const elapsedMs = Date.now() - startMs
              resolve({
                chunks: chunkSequence.length,
                totalBytes,
                elapsedMs,
                ttfbMs,
                chunkSequence,
                throughputMbps: throughputMbps(totalBytes, elapsedMs)
              })
            }
          })

          res.on('error', (err) => {
            idleHelper.clear()
            aborted = true
            reject(err)
          })
        })

        req.on('error', (err) => {
          idleHelper.clear()
          aborted = true
          reject(err)
        })

        req.end()
      })
    }
  }
}

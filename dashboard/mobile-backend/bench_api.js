import { clampBytes, clampChunks, createTokenBucket, createBoundedMap } from './bench_limits.js'

const MAX_BODY_SIZE = 10 * 1024 * 1024
const DEFAULT_CHUNKS = 10
const MAX_CHUNKS = 1000
const CHUNK_SIZE_BYTES = 1024

export function createBenchApiRouter(opts = {}) {
  const rateLimiterCap = opts.rateLimiterCap || 10000
  const rateLimiters = createBoundedMap(rateLimiterCap)

  function getRateLimiter(peerId) {
    if (!rateLimiters.has(peerId)) {
      rateLimiters.set(peerId, createTokenBucket({
        tokensPerSecond: 100,
        maxBurst: 10
      }))
    }
    return rateLimiters.get(peerId)
  }

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    const peerId = req.gatePeer || req.socket.remoteAddress || 'unknown'

    try {
      if (req.method === 'GET' && pathname === '/bench/ping') {
        const limiter = getRateLimiter(peerId)
        if (!limiter.tryConsume()) {
          res.writeHead(429, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'rate limited' })
          )
          return true
        }

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({
            ok: true,
            timestamp: Date.now()
          })
        )
        return true
      }

      if (req.method === 'POST' && pathname === '/bench/echo') {
        const limiter = getRateLimiter(peerId)
        if (!limiter.tryConsume()) {
          res.writeHead(429, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'rate limited' })
          )
          return true
        }

        const chunks = []
        let totalSize = 0

        for await (const chunk of req) {
          totalSize += chunk.length
          const sizeCheckResult = clampBytes(totalSize, MAX_BODY_SIZE)
          if (sizeCheckResult instanceof Error) {
            res.writeHead(sizeCheckResult.statusCode, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: 'payload too large' })
            )
            return true
          }

          chunks.push(chunk)
        }

        const body = Buffer.concat(chunks).toString()

        if (body.length === 0) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'empty body' })
          )
          return true
        }

        let payload
        try {
          payload = JSON.parse(body)
        } catch {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'invalid json' })
          )
          return true
        }

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({
            ok: true,
            echo: payload,
            timestamp: Date.now()
          })
        )
        return true
      }

      if (req.method === 'GET' && pathname === '/bench/stream') {
        const limiter = getRateLimiter(peerId)
        if (!limiter.tryConsume()) {
          res.writeHead(429, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'rate limited' })
          )
          return true
        }

        const chunksResult = clampChunks(url.searchParams.get('chunks'), DEFAULT_CHUNKS, MAX_CHUNKS)
        if (chunksResult instanceof Error) {
          res.writeHead(chunksResult.statusCode, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: chunksResult.message })
          )
          return true
        }
        const chunks = chunksResult

        res.writeHead(200, {
          'Content-Type': 'application/x-ndjson',
          'Transfer-Encoding': 'chunked'
        })

        let aborted = false
        let onAbort = null

        req.on('close', () => {
          aborted = true
          if (onAbort) onAbort()
        })

        try {
          for (let i = 0; i < chunks; i++) {
            if (aborted) {
              break
            }

            const metadata = JSON.stringify({
              ok: true,
              index: i,
              timestamp: Date.now(),
              bytes: CHUNK_SIZE_BYTES
            }) + '\n'

            let shouldContinue = res.write(metadata)
            if (!shouldContinue) {
              await new Promise(resolve => {
                onAbort = resolve
                res.once('drain', resolve)
              })
            }

            const payload = Buffer.alloc(CHUNK_SIZE_BYTES).fill(0)
            shouldContinue = res.write(payload)
            if (!shouldContinue) {
              await new Promise(resolve => {
                onAbort = resolve
                res.once('drain', resolve)
              })
            }
          }
        } finally {
          // noop
        }

        res.end()
        return true
      }

      return false
    } catch (err) {
      console.error(`Bench API error: ${err.message}`)
      if (!res.headersSent) {
        res.writeHead(500, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: false, error: 'internal server error' })
        )
      } else {
        res.destroy ? res.destroy() : res.end()
      }
      return true
    }
  }
}

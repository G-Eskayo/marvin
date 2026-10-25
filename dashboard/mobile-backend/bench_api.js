import { createTokenBucket, createBoundedMap, clampChunks, MAX_ECHO_BODY_BYTES } from './bench_limits.js'

const DEFAULT_TOKENS_PER_SECOND = 100
const DEFAULT_MAX_BURST = 1000
const DEFAULT_MAX_PEERS = 100

export function createBenchApiRouter(opts = {}) {
  const tokensPerSecond = opts.tokensPerSecond || DEFAULT_TOKENS_PER_SECOND
  const maxBurst = opts.maxBurst || DEFAULT_MAX_BURST
  const maxPeers = opts.maxPeers || DEFAULT_MAX_PEERS

  const peerBuckets = createBoundedMap(maxPeers)

  function getBucket(peer) {
    if (!peerBuckets.has(peer)) {
      peerBuckets.set(peer, createTokenBucket({ tokensPerSecond, maxBurst }))
    }
    return peerBuckets.get(peer)
  }

  function checkRateLimit(peer, tokens = 1) {
    const bucket = getBucket(peer)
    return bucket.tryConsume(tokens)
  }

  return async (req, res) => {
    let pathname
    let url
    let peer = req.gatePeer

    try {
      url = new URL(req.url, `http://${req.headers.host}`)
      pathname = url.pathname
    } catch (err) {
      res.writeHead(400, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: false, error: 'invalid URL' })
      )
      return true
    }

    if (!peer) {
      res.writeHead(400, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: false, error: 'req.gatePeer not set' })
      )
      return true
    }

    try {
      if (req.method === 'GET' && pathname === '/bench/ping') {
        if (!checkRateLimit(peer, 1)) {
          res.writeHead(429, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'rate limited' })
          )
          return true
        }

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, message: 'pong' })
        )
        return true
      }

      if (req.method === 'POST' && pathname === '/bench/echo') {
        if (!checkRateLimit(peer, 10)) {
          res.writeHead(429, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'rate limited' })
          )
          return true
        }

        const chunks = []
        let totalBytes = 0

        for await (const chunk of req) {
          totalBytes += chunk.length
          if (totalBytes > MAX_ECHO_BODY_BYTES) {
            req.destroy()
            res.writeHead(413, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: 'payload too large' })
            )
            return true
          }
          chunks.push(chunk)
        }

        const echoBuffer = Buffer.concat(chunks)
        res.writeHead(200, { 'Content-Type': 'application/octet-stream' })
        res.end(echoBuffer)
        return true
      }

      if (req.method === 'GET' && pathname === '/bench/stream') {
        const chunksParam = url.searchParams.get('chunks')
        if (!chunksParam) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'missing chunks parameter' })
          )
          return true
        }

        const chunksParsed = parseInt(chunksParam, 10)
        const chunks = clampChunks(chunksParsed)

        if (isNaN(chunksParsed)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'invalid chunks parameter' })
          )
          return true
        }

        if (!checkRateLimit(peer, chunks)) {
          res.writeHead(429, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'rate limited' })
          )
          return true
        }

        res.writeHead(200, { 'Content-Type': 'application/octet-stream' })

        let closed = false
        const closePromise = new Promise((resolve) => {
          req.once('close', () => {
            closed = true
            resolve()
          })
        })

        for (let i = 0; i < chunks; i++) {
          if (closed) break

          const chunk = Buffer.alloc(1024)
          chunk.writeUInt16BE(i, 0)
          const canContinue = res.write(chunk)

          if (!canContinue) {
            await Promise.race([
              new Promise((resolve) => res.once('drain', resolve)),
              closePromise
            ])
          }
        }

        if (!closed) {
          res.end()
        }
        return true
      }

      return false
    } catch (err) {
      if (!res.headersSent) {
        res.writeHead(500, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: false, error: err.message })
        )
      }
      return true
    }
  }
}

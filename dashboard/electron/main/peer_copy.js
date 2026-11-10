// The producer's live copy for a standby Mac (marvin#1223; Gil 2026-11-09: "the producing Mac's copy, labelled
// '<Mac>, as of N min ago'"). This Mac's own copy of a primary-made file (Health, ticket-agent proposals, the board
// registry) is used while it is within its tolerance. Past it, and only when this Mac isn't the producer, the
// producer's GET /copy/<name> (webhook-server/copy_route.js) is asked once, and the newer of the two is shown, with
// `from` saying which. Producer asleep or Tailscale down: our own copy, stale, with its age and Mac, never as current.
// One fetch per name per CACHE_MS however many screens read at once (read-through, no timer).
import http from 'http'
import { readStamped, fromData, newerCopy } from './stamped.js'
import { isPrimaryHost, primaryHostTailscaleName } from './device_identity.js'

export const CACHE_MS = 60_000
const TIMEOUT_MS = 2000
const MAX_BYTES = 2 * 1024 * 1024

export function fetchCopyFrom(host, name, { port = 7878, timeoutMs = TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    let done = false
    const finish = (v) => { if (!done) { done = true; resolve(v) } }
    const req = http.get({ host, port, path: `/copy/${encodeURIComponent(name)}`, timeout: timeoutMs }, (res) => {
      if (res.statusCode !== 200) { res.resume(); return finish(null) }
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (chunk) => {
        body += chunk
        if (body.length > MAX_BYTES) { req.destroy(); finish(null) }
      })
      res.on('end', () => { try { finish(JSON.parse(body)) } catch { finish(null) } })
    })
    req.on('timeout', () => { req.destroy(); finish(null) })
    req.on('error', () => finish(null))
  })
}

export function createPeerCopies({ isProducer = () => isPrimaryHost(), producerHost = () => primaryHostTailscaleName(),
  fetchCopy = fetchCopyFrom, now = Date.now } = {}) {
  const cache = new Map() // name -> { at, promise }

  function producerCopy(name, defaultToleranceS) {
    const hit = cache.get(name)
    if (hit && now() - hit.at < CACHE_MS) return hit.promise
    const host = producerHost()
    const promise = host
      ? Promise.resolve(fetchCopy(host, name)).then((data) => fromData(data, { now: now(), defaultToleranceS })).catch(() => null)
      : Promise.resolve(null)
    cache.set(name, { at: now(), promise })
    return promise
  }

  async function read(name, localPath, { defaultToleranceS = 600 } = {}) {
    const local = { ...readStamped(localPath, { now: now(), defaultToleranceS }), from: 'local' }
    if (!local.stale || isProducer()) return local
    const peer = await producerCopy(name, defaultToleranceS)
    if (!peer || peer.missing || peer.ageS == null) return { ...local, producerUnreachable: true }
    const best = newerCopy(local, { ...peer, from: 'producer' })
    return best.from === 'producer' ? best : { ...local, producerOlder: true }
  }

  return { read, clear: () => cache.clear() }
}

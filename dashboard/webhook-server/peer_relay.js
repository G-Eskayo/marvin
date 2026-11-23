// Generic peer relay: post a message to each peer on a specified path, in order, with backoff and timeout.
// Used by both merge-stage and change notifications.
export const DEFAULT_RELAY_TIMEOUT_MS = 2000
export const DEFAULT_PEER_QUIET_MS = 60_000

export function createPeerRelay({
  peers = () => [],
  post,
  path = '/relay',
  port = 7878,
  timeoutMs = DEFAULT_RELAY_TIMEOUT_MS,
  quietMs = DEFAULT_PEER_QUIET_MS,
  now = Date.now,
  log = () => {}
}) {
  const lines = new Map() // host -> { tail: Promise, quietUntil: ms }

  function send(host, body) {
    const line = lines.get(host) || { tail: Promise.resolve(), quietUntil: 0 }
    lines.set(host, line)
    if (line.quietUntil > now()) return line.tail
    line.tail = line.tail.then(async () => {
      if (line.quietUntil > now()) return // went quiet while this one waited: drop it, the next event catches up
      try {
        const res = await post(`http://${host}:${port}${path}`, body, { timeoutMs })
        if (res && res.ok === false) throw new Error(`answered ${res.status}`)
      } catch (e) {
        line.quietUntil = now() + quietMs
        log(`[peer-relay] ${host} did not take message on ${path} (${String(e?.message || e).slice(0, 80)}); skipped for ${Math.round(quietMs / 1000)} s`)
      }
    })
    return line.tail
  }

  return function relay(message) {
    if (!message) return Promise.resolve()
    let list = []
    try { list = peers() || [] } catch { list = [] }
    return Promise.allSettled(list.filter((p) => p && p.host).map((p) => send(p.host, message)))
  }
}

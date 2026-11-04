// Every Mac sees every merge as it happens (marvin#231 follow-up): the owner, on the MacBook, watched a merge the
// queue started on the Mac mini and saw "Merging" with no stage strip, because the merge server only told the
// dashboard on its own Mac. Now each stage event is also posted to the webhook on every other registered Mac
// (POST /merge-stage), which hands it to the dashboard there as topic 'merge', exactly like a local one.
//
//   relay(message)   message = { url, event, progress }: the stage event, plus the merge's whole progress so far, so
//                    a Mac that missed events (asleep, a post lost, out of order) catches up from the next one.
//   Best effort and never in the merge's way: relay() returns at once; each peer has its own line, one post at a
//   time (so events arrive in order), each bounded by a short timeout. A peer that doesn't answer is skipped for a
//   while (no posts piling up for a sleeping Mac); the next event after that tries it again. Triggers only: nothing
//   is sent unless a merge emits an event. O(peers) posts per event, about 10 events per merge.
//
//   createLiveMerges(): the latest progress of each merge on this Mac, for GET /merge-progress, so a dashboard that
//   opens mid-merge reads where it is once, instead of waiting for the next event. Bounded (newest `cap` kept).
//   allowedPeerAddress(ip): /merge-stage is for the other Macs only: loopback or the Tailscale ranges.

export const RELAY_TIMEOUT_MS = 2000
export const PEER_QUIET_MS = 60_000

const URL_OK = (u) => typeof u === 'string' && u.startsWith('https://github.com/') && u.length < 300

export function createStageRelay({ peers = () => [], post, port = 7878, timeoutMs = RELAY_TIMEOUT_MS, quietMs = PEER_QUIET_MS, now = Date.now, log = () => {} }) {
  const lines = new Map() // host -> { tail: Promise, quietUntil: ms }
  function send(host, body) {
    const line = lines.get(host) || { tail: Promise.resolve(), quietUntil: 0 }
    lines.set(host, line)
    if (line.quietUntil > now()) return line.tail
    line.tail = line.tail.then(async () => {
      if (line.quietUntil > now()) return // went quiet while this one waited: drop it, the next event catches up
      try {
        const res = await post(`http://${host}:${port}/merge-stage`, body, { timeoutMs })
        if (res && res.ok === false) throw new Error(`answered ${res.status}`)
      } catch (e) {
        line.quietUntil = now() + quietMs
        log(`[merge-relay] ${host} did not take a stage event (${String(e?.message || e).slice(0, 80)}); skipped for ${Math.round(quietMs / 1000)} s`)
      }
    })
    return line.tail
  }
  return function relay(message) {
    if (!message || !URL_OK(message.url) || !message.event) return Promise.resolve()
    let list = []
    try { list = peers() || [] } catch { list = [] }
    const body = { url: message.url, event: message.event, progress: message.progress || null }
    return Promise.allSettled(list.filter((p) => p && p.host).map((p) => send(p.host, body)))
  }
}

export function createLiveMerges({ cap = 50, now = Date.now } = {}) {
  const live = new Map() // url -> { url, progress, machine, at }
  return {
    update(url, progress, machine = null) {
      if (!URL_OK(url) || !progress) return
      live.delete(url)
      live.set(url, { url, progress, machine, at: now() })
      while (live.size > cap) live.delete(live.keys().next().value)
    },
    get: (url) => live.get(url) || null,
    // Merges still running (no outcome yet); a finished one is kept for get(url) so a late reader sees how it ended.
    running: () => [...live.values()].filter((m) => !m.progress.outcome)
  }
}

// The Mac's own loopback, or a Tailscale address (100.64.0.0/10, fd7a:115c:a1e0::/48), which only the owner's Macs
// and phone have. Anything else is refused.
export function allowedPeerAddress(ip) {
  const a = String(ip || '').replace(/^::ffff:/, '')
  if (a === '127.0.0.1' || a === '::1') return true
  const m = a.match(/^100\.(\d+)\.\d+\.\d+$/)
  if (m && Number(m[1]) >= 64 && Number(m[1]) <= 127) return true
  return /^fd7a:115c:a1e0:/i.test(a)
}

// A /merge-stage body made safe to hand on: a GitHub PR url, an event object, and the progress object or null.
export function cleanStageMessage(body) {
  if (!body || !URL_OK(body.url) || !body.event || typeof body.event !== 'object') return null
  const progress = body.progress && typeof body.progress === 'object' && body.progress.stages && typeof body.progress.stages === 'object' ? body.progress : null
  return { url: body.url, event: body.event, progress }
}

// What a merge's tracker emits goes three ways, the same message each time: the live record (GET /merge-progress), the
// dashboard on this Mac, and the other Macs. Whoever started the merge (the queue, a click, the phone), so all show it.
// Never throws and never waits: `local` and `relay` are fire-and-forget.
export function stageFanOut({ url, machineId = null, live, local, relay }) {
  return (event, progress) => {
    const message = { url, event, progress }
    try { live?.update(url, progress, machineId) } catch { /* bookkeeping only */ }
    try { local?.(message) } catch { /* no dashboard open here */ }
    try { Promise.resolve(relay?.(message)).catch(() => {}) } catch { /* a peer problem never reaches the merge */ }
  }
}

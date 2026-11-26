// Fire-and-forget relay of GitHub changes to peers (every other owner Mac), so their dashboards see the
// same triggers as this one when a webhook is exposed via Funnel on the primary. Each peer runs its own
// change-watch on GitHub, but that takes ~20s; a peer relaying GitHub to localhost is instant.

export async function relayGithubChange({ peers = [], repo, event, post }) {
  if (!peers.length) return

  const body = { repo, event }
  const relays = peers.map((peer) => {
    const url = `http://${peer.host}:${peer.port || 7878}/github-relay`
    // Fire-and-forget with timeout.
    return Promise.resolve().then(() =>
      Promise.race([
        post(url, body),
        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 5000))
      ])
    ).catch(() => {}) // Swallow failures: peers may be asleep or offline.
  })

  // Return before all settle: the goal is to not block the webhook handler.
  Promise.allSettled(relays).catch(() => {})
}

export function receiveGithubRelay(body) {
  if (!body || typeof body !== 'object') return null
  const { repo, event } = body
  if (typeof repo !== 'string' || typeof event !== 'string') return null
  return { repo, event }
}

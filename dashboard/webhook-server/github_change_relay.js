import { createPeerRelay } from './peer_relay.js'

// Relay a GitHub change notification to other Macs via POST /gh-change.
// peers, post, etc. are injected (same as merge_stage_relay).
export function createChangeRelay({ peers = () => [], post, port = 7878, timeoutMs = 2000, quietMs = 60_000, now = Date.now, log = () => {} }) {
  const relay = createPeerRelay({ peers, post, path: '/gh-change', port, timeoutMs, quietMs, now, log })
  return function changeRelay(message) {
    if (!message) return Promise.resolve()
    return relay(message)
  }
}

// Sanitize a /gh-change body for relay: a repo name and optional event data.
export function cleanChangeMessage(body) {
  if (!body || typeof body !== 'object') return null
  const repo = typeof body.repo === 'string' ? body.repo : null
  if (!repo) return null
  // The repo name is validated by the sender; we pass through any event data it included.
  const event = body.event && typeof body.event === 'object' ? body.event : null
  return { repo, event }
}

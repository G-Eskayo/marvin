import { allowedPeerAddress } from './merge_stage_relay.js'

// marvin#566: relay GitHub webhook changes to peer Macs (Mini → Laptop and vice versa).
// The Mini with the Tailscale Funnel receives webhooks and fans out to peers via /github-change.

export async function relayGithubChange({ repo, peers = [], post }) {
  if (!peers.length) return
  const targets = peers.map((p) => () => post(
    `http://${p.host}:7878/github-change`,
    { repo },
    { timeoutMs: 5000 }
  ))
  const results = await Promise.allSettled(targets.map((send) => Promise.resolve().then(send)))
  const told = results.filter((r) => r.status === 'fulfilled').length
  if (told > 0) console.log(`[github-webhook] relayed ${repo} to ${told} of ${peers.length} peers`)
}

// Receiver side: handle /github-change requests from a peer webhook relay.
// Validates source address (loopback or allowed peer), parses repo, validates repo against allow-list, calls onChange.
export function handleGithubChangeRequest({ method, url, headers, body, remoteAddress }, { onChange, allowedPeerFn = allowedPeerAddress, watchedRepos = () => [] }) {
  if (!allowedPeerFn(remoteAddress)) {
    return { status: 403, body: JSON.stringify({ ok: false, error: 'forbidden' }) }
  }

  let payload
  try {
    payload = JSON.parse(body)
  } catch {
    return { status: 400, body: JSON.stringify({ ok: false, error: 'invalid json' }) }
  }

  const repo = typeof payload.repo === 'string' ? payload.repo : ''
  if (!repo) {
    return { status: 400, body: JSON.stringify({ ok: false, error: 'missing repo' }) }
  }

  // Validate repo is in the watched set.
  if (!watchedRepos().includes(repo)) {
    return { status: 403, body: JSON.stringify({ ok: false, error: 'repo not in scope' }) }
  }

  // Fire onChange without awaiting; respond at once.
  onChange(repo)

  return { status: 200, body: JSON.stringify({ ok: true }) }
}

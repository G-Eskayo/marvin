import { describe, it, expect, afterEach } from 'vitest'
import { createServer } from 'http'
import { announceMergeHost, relayMergeHostUp } from '../webhook-server/merge_host_announce.js'

// marvin#762: a merge machine coming back is the trigger for retrying saved approvals. Its webhook announces itself
// on startup to the dashboard on its own Mac and to the webhook on every other Mac (which relays it to its dashboard).
const servers = []
afterEach(async () => { await Promise.all(servers.splice(0).map((s) => new Promise((r) => s.close(() => r())))) })
function listen(onBody) {
  const s = createServer((req, res) => { let raw = ''; req.on('data', (c) => (raw += c)); req.on('end', () => { onBody(req.url, JSON.parse(raw || '{}')); res.end('{}') }) })
  servers.push(s)
  return new Promise((r) => s.listen(0, '127.0.0.1', () => r(s.address().port)))
}
const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(500) })

describe('announceMergeHost', () => {
  it('tells this Mac\'s dashboard and every peer\'s webhook that this machine can merge again', async () => {
    const got = []
    const dash = await listen((url, body) => got.push(['dash', url, body]))
    const peer = await listen((url, body) => got.push(['peer', url, body]))
    await announceMergeHost({ machineId: 'mac-mini-1', localRefreshUrl: `http://127.0.0.1:${dash}/refresh`, peers: [{ id: 'macbook-pro-1', host: '127.0.0.1' }], peerPort: peer, post })
    expect(got.sort()).toEqual([
      ['dash', '/refresh', { topics: ['merge-host'], source: 'merge-host-up', machine: 'mac-mini-1' }],
      ['peer', '/merge-host-up', { machine: 'mac-mini-1' }]
    ])
  })

  it('a peer that is down (the other Mac asleep) never throws, and does not hold up the others', async () => {
    const got = []
    const dash = await listen((url, body) => got.push(body))
    const r = await announceMergeHost({ machineId: 'm', localRefreshUrl: `http://127.0.0.1:${dash}/refresh`, peers: [{ id: 'x', host: '127.0.0.1' }], peerPort: 1, post })
    expect(got).toHaveLength(1)
    expect(r).toEqual({ told: 1, of: 2 })
  })
})

describe('relayMergeHostUp (POST /merge-host-up on the receiving Mac)', () => {
  it('forwards to the dashboard here as the merge-host topic, naming the machine', async () => {
    const got = []
    const dash = await listen((url, body) => got.push(body))
    await relayMergeHostUp({ machine: 'mac-mini-1' }, { localRefreshUrl: `http://127.0.0.1:${dash}/refresh`, post })
    expect(got).toEqual([{ topics: ['merge-host'], source: 'merge-host-up', machine: 'mac-mini-1' }])
  })

  it('junk in the body is not passed on: the machine is a short plain id or "unknown"', async () => {
    const got = []
    const dash = await listen((url, body) => got.push(body))
    await relayMergeHostUp({ machine: '<script>'.repeat(20) }, { localRefreshUrl: `http://127.0.0.1:${dash}/refresh`, post })
    await relayMergeHostUp(null, { localRefreshUrl: `http://127.0.0.1:${dash}/refresh`, post })
    expect(got.map((b) => b.machine)).toEqual(['unknown', 'unknown'])
  })
})

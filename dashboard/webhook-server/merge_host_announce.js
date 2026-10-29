// marvin#762: "a merge machine came back" as a trigger, so saved approvals are retried without polling. On startup
// (launchd starts it at boot and after a crash) this webhook tells the dashboard on its own Mac, and the webhook on
// every other registered Mac, which relays it to the dashboard there (POST /merge-host-up -> topic 'merge-host').
// Best effort: a Mac that is asleep misses it, and its own startup/wake triggers cover it. O(peers) posts, each
// bounded by the post's own timeout, all at once.
const ID = /^[a-z0-9][a-z0-9-]{0,63}$/

const cleanId = (v) => (typeof v === 'string' && ID.test(v) ? v : 'unknown')
const payload = (machine) => ({ topics: ['merge-host'], source: 'merge-host-up', machine: cleanId(machine) })

export async function announceMergeHost({ machineId, localRefreshUrl, peers = [], peerPort = 7878, post }) {
  const targets = [
    () => post(localRefreshUrl, payload(machineId)),
    ...peers.map((p) => () => post(`http://${p.host}:${peerPort}/merge-host-up`, { machine: cleanId(machineId) }))
  ]
  const results = await Promise.allSettled(targets.map((send) => Promise.resolve().then(send)))
  return { told: results.filter((r) => r.status === 'fulfilled').length, of: targets.length }
}

export async function relayMergeHostUp(body, { localRefreshUrl, post }) {
  try { await post(localRefreshUrl, payload(body?.machine)) } catch { /* no dashboard open here: nothing to retry */ }
}

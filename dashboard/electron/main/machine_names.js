import { machineLabel } from '../../src/lib/merge_progress.js'
import { readNetworkRegistry } from './github_feed.js'

// What each machine is called on screen (owner, PR #1030, worker-name): the network registry's own display name
// (~/.claude/marvin-network.json `display_name`, `display` or `name`), else the name the merge screens already give an
// id (merge_progress.js machineLabel: "mac-mini-1" -> "Mac mini"), else the raw id. Read in the main process only.
export function machineNames(devices = readNetworkRegistry()) {
  const out = {}
  for (const [id, d] of Object.entries(devices && typeof devices === 'object' ? devices : {})) {
    const own = [d?.display_name, d?.display, d?.name].find((v) => typeof v === 'string' && v.trim())
    out[id] = own ? own.trim() : machineLabel(id)
  }
  return out
}

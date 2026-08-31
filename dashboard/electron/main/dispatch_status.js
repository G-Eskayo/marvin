import { readFileSync, existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// task_dispatch.py's own state file -- the same one it writes on every
// dispatch and clears on completion (lib/task_dispatch.py's
// _build_wrapper_script). No IPC/subprocess to Python needed: this
// machine's current task is just a JSON file on disk.
//
// Local-machine only, same scoping reasoning as mr_seen.js -- showing the
// *other* machine's status would mean SSHing from the Electron main
// process (task_dispatch.py already does this for the remote machine via
// _read_remote_dispatch_state), which is a real extension, not this cut.
export const DISPATCH_STATE_PATH = path.join(homedir(), '.claude', 'dispatch-state.json')

export function readDispatchStatus(statePath = DISPATCH_STATE_PATH) {
  if (!existsSync(statePath)) return { busy: false, task: null, startedAt: null }
  try {
    const data = JSON.parse(readFileSync(statePath, 'utf-8'))
    if (!data.busy) return { busy: false, task: null, startedAt: null }
    return { busy: true, task: data.task || null, startedAt: data.started_at || null }
  } catch {
    return { busy: false, task: null, startedAt: null }
  }
}

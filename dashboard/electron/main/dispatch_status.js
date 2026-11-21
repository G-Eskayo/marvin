import { readStamped } from './stamped.js'
import { homedir } from 'os'
import path from 'path'
import fs from 'fs'

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
export const TASKS_DIR = path.join(homedir(), '.claude', 'dispatch', 'tasks')

function isPidAlive(pid) {
  if (!pid || pid <= 0) return false
  try {
    // process.kill(pid, 0) on Unix: signal 0 returns without sending anything, just checks existence
    process.kill(pid, 0)
    return true
  } catch (e) {
    return false
  }
}

export function readDispatchStatus(statePath = DISPATCH_STATE_PATH, tasksDir = TASKS_DIR) {
  const data = readStamped(statePath, { defaultToleranceS: 3600 }).value
  if (!data || !data.busy) return { busy: false, task: null, startedAt: null }

  // Cross-check: if task_id is present, verify the task record's pid is still alive
  const taskId = data.task_id
  if (taskId) {
    try {
      const taskRecordPath = path.join(tasksDir, `${taskId}.json`)
      if (fs.existsSync(taskRecordPath)) {
        const taskRecord = JSON.parse(fs.readFileSync(taskRecordPath, 'utf-8'))
        const pid = taskRecord.pid
        if (pid && !isPidAlive(pid)) {
          // PID is dead but state file still says busy — treat as not busy
          return { busy: false, task: null, startedAt: null }
        }
      }
    } catch (e) {
      // If we can't read the task record, trust the state file
    }
  }

  return { busy: true, task: data.task || null, startedAt: data.started_at || null }
}

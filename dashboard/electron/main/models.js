import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const REGISTRY_CLI = path.join(homedir(), '.agents', 'lib', 'model_registry.py')
const QUEUE_CLI = path.join(homedir(), '.agents', 'lib', 'model_queue.py')

function defaultRun(args, cli = REGISTRY_CLI) {
  return new Promise((resolve, reject) =>
    execFile(PY, [cli, ...args], { timeout: 10000 }, (err, stdout, stderr) =>
      err ? reject(new Error((stderr || err.message).trim())) : resolve(stdout)
    )
  )
}

export async function listModels({ run = defaultRun } = {}) {
  const output = await run(['get'], REGISTRY_CLI)
  return JSON.parse(output)
}

export async function currentQueue(machine = null, { run = defaultRun } = {}) {
  const args = ['current']
  if (machine) {
    args.push('--machine', machine)
  }
  const output = await run(args, QUEUE_CLI)
  try {
    const lines = output.trim().split('\n')
    const tasks = []
    let current = ''
    for (const line of lines) {
      current += line + '\n'
      if (line === '}') {
        try {
          tasks.push(JSON.parse(current.trim()))
          current = ''
        } catch {
          // multi-object output, keep accumulating
        }
      }
    }
    return tasks
  } catch {
    return []
  }
}

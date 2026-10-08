import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

const VENV_PYTHON = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const REGISTRY_CLI = path.join(homedir(), '.agents-pipeline-worktrees', 'pipeline-g-eskayo-marvin-290', 'lib', 'model_registry.py')
const QUEUE_CLI = path.join(homedir(), '.agents-pipeline-worktrees', 'pipeline-g-eskayo-marvin-290', 'lib', 'model_queue.py')

function defaultRun(args, cli) {
  return new Promise((resolve, reject) =>
    execFile(VENV_PYTHON, [cli, ...args], { timeout: 20000 }, (err, stdout, stderr) =>
      err ? reject(new Error((stderr || err.message).trim())) : resolve(stdout)
    )
  )
}

export async function getModels({ run = defaultRun } = {}) {
  const registry = JSON.parse(await run(['get'], REGISTRY_CLI))
  return registry
}

export async function getCurrentQueue(machine = null, { run = defaultRun } = {}) {
  const args = machine ? ['current', '--machine', machine] : ['current']
  const queue = JSON.parse(await run(args, QUEUE_CLI))
  return queue
}

export async function getModelsWithQueue(machine = null, { run = defaultRun } = {}) {
  const registry = await getModels({ run })
  const queue = await getCurrentQueue(machine, { run })
  return { registry, queue }
}

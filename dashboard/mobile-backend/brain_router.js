import { execFile } from 'child_process'
import { promisify } from 'util'
import { homedir } from 'os'
import path from 'path'

const execFileP = promisify(execFile)

// Resolve the route.py script in the MARVIN ~/.agents directory
function resolveRouteScript() {
  const agentsHome = path.join(homedir(), '.agents')
  return path.join(agentsHome, 'skills', 'route', 'scripts', 'route.py')
}

// Resolve the MARVIN venv python interpreter
function resolveVenvPython() {
  const venvPython = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
  return venvPython
}

// Classify a text prompt and map the intent to a brain routing decision
export async function classifyBrain(text, opts = {}) {
  const routeScript = resolveRouteScript()
  const venvPython = resolveVenvPython()

  try {
    const { stdout } = await execFileP(venvPython, [routeScript, text, '--json'])
    const result = JSON.parse(stdout.trim())

    // Map intents to brain routing
    // 'fast' intents: recall (ChromaDB), research (skill)
    // 'deep' intents: coding, architecture
    const fastIntents = ['recall', 'research']
    const isFast = fastIntents.includes(result.intent)

    return {
      intent: result.intent,
      method: result.method,
      score: result.score,
      brainType: isFast ? 'fast' : 'deep'
    }
  } catch (err) {
    // Fall back to 'deep' brain on subprocess failure
    return {
      intent: null,
      method: 'error',
      score: 0,
      brainType: 'deep',
      error: err.message
    }
  }
}

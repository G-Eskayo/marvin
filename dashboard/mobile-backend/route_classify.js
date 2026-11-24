// Bridge to the route classifier (skills/route/scripts/route.py). Only its keyword pass runs here: it is
// deterministic, needs no Ollama, and costs ~30 ms, inside the voice latency budget (ADR 0075 point 5).
import { execFile } from 'child_process'
import { existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { fileURLToPath } from 'url'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const VENV_PYTHON = path.join(homedir(), '.agents', 'venv', 'bin', 'python')

const SCRIPT = `
import json, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import route
intent, hits = route.classify(sys.stdin.read()[: route.MAX_ROUTE_CHARS])
print(json.dumps({"intent": intent, "hits": hits}))
`

function defaultPython() {
  return process.env.MARVIN_PYTHON || (existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3')
}

// Resolves { intent, hits }, or null if the classifier could not run (no Python, a crash, a timeout).
export function routeClassify(text, { python = defaultPython(), timeoutMs = 1000 } = {}) {
  return new Promise((resolve) => {
    let child
    try {
      child = execFile(
        python,
        ['-c', SCRIPT, path.join(REPO_ROOT, 'skills', 'route', 'scripts'), path.join(REPO_ROOT, 'lib')],
        { timeout: timeoutMs, maxBuffer: 64 * 1024 },
        (err, stdout) => {
          if (err) return resolve(null)
          try {
            const r = JSON.parse(stdout)
            resolve(typeof r.hits === 'number' ? r : null)
          } catch {
            resolve(null)
          }
        }
      )
    } catch {
      return resolve(null)
    }
    child.on('error', () => resolve(null))
    child.stdin?.on('error', () => {})
    child.stdin?.end(String(text ?? ''))
  })
}

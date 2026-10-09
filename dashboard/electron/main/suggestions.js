import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CLI = path.join(homedir(), '.agents', 'lib', 'suggestions_list.py')

function defaultRun() {
  return new Promise((resolve, reject) =>
    execFile(PY, [CLI], { timeout: 10000 }, (err, stdout) => (err ? reject(err) : resolve(stdout)))
  )
}

export async function listSuggestions({ run = defaultRun } = {}) {
  let suggestions
  try {
    suggestions = JSON.parse(await run())
  } catch (err) {
    return { suggestions: [], error: `Could not read suggestions: ${err.message}` }
  }
  return { suggestions, error: null }
}

import { execFile } from 'child_process'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)

// Separated from the HTTP plumbing in index.js so this -- the part that
// actually matters -- is unit-testable without spinning up a real server
// or hitting real GitHub.
export async function mergePr(prUrl, exec = execFileAsync) {
  if (typeof prUrl !== 'string' || !prUrl.startsWith('https://github.com/')) {
    throw new Error(`Not a GitHub PR URL: ${prUrl}`)
  }
  await exec('gh', ['pr', 'merge', prUrl, '--merge'])
}

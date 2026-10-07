import { spawn } from 'child_process'
import { createInterface } from 'readline'
import { homedir } from 'os'
import { existsSync } from 'fs'
import path from 'path'

// Resolve the claude binary. Check ~/.local/bin/claude first, then fall back to PATH lookup.
function resolveClaudeBinary() {
  const localBin = path.join(homedir(), '.local', 'bin', 'claude')
  if (existsSync(localBin)) return localBin
  return 'claude'
}

// Normalise a raw event from the CLI stream-json output.
// Returns zero or more normalised events: {type: 'session'|'text'|'tool_use'|'result'|'error', ...}
export function normaliseEvent(rawEvent) {
  if (!rawEvent) return []

  try {
    const event = typeof rawEvent === 'string' ? JSON.parse(rawEvent) : rawEvent
    const results = []

    // Session init events carry a session ID
    if (event.type === 'system' && event.session_id) {
      results.push({
        type: 'session',
        sessionId: event.session_id
      })
    }

    // Assistant messages carry text and/or tool_use blocks
    if (event.type === 'assistant' && event.message) {
      const content = event.message.content || []
      for (const block of content) {
        if (block.type === 'text' && block.text) {
          results.push({
            type: 'text',
            text: block.text
          })
        }
        if (block.type === 'tool_use') {
          results.push({
            type: 'tool_use',
            name: block.name,
            input: block.input
          })
        }
      }
    }

    // Streaming partial text deltas (when CLI emits fine-grained updates)
    if (event.type === 'stream_event' && event.delta && event.delta.type === 'text_delta') {
      results.push({
        type: 'text',
        text: event.delta.text
      })
    }

    // Final result event — carries usage, cost, duration, error flag, final session ID
    if (event.type === 'result') {
      const usage = event.usage || {}
      results.push({
        type: 'result',
        text: event.result || '',
        sessionId: event.session_id,
        costUsd: event.total_cost_usd || 0,
        durationMs: event.duration_ms || 0,
        isError: event.is_error || false
      })
    }

    return results
  } catch (err) {
    // Malformed JSON lines are silently skipped, not surfaced as errors
    // (the CLI may emit debug output that isn't valid JSON)
    return []
  }
}

// Async generator that streams normalised events from a claude CLI session.
// Spawns the CLI with --output-format stream-json and reads stdout line-by-line.
export async function* runSession({ message, sessionId, spawnFn, cwd } = {}) {
  const claudeBin = resolveClaudeBinary()
  const actualSpawnFn = spawnFn || spawn
  const actualCwd = cwd || homedir()

  // Build CLI arguments
  const args = [
    '-p', message,
    '--output-format', 'stream-json',
    '--verbose',
    '--include-partial-messages',
    '--permission-mode', 'dontAsk'
  ]

  // Add --resume if sessionId is provided
  if (sessionId) {
    args.push('--resume', sessionId)
  }

  let child
  try {
    child = actualSpawnFn(claudeBin, args, { cwd: actualCwd })
  } catch (err) {
    yield {
      type: 'error',
      message: `Failed to spawn claude: ${err.message}`
    }
    return
  }

  // Set up line-by-line reader for stdout
  const rl = createInterface({
    input: child.stdout,
    crlfDelay: Infinity
  })

  // Track exit code separately
  let exitCode = null
  const exitPromise = new Promise((resolve) => {
    child.on('exit', (code) => {
      exitCode = code
      resolve(code)
    })
  })

  // Yield each normalised event as it arrives
  try {
    for await (const line of rl) {
      const events = normaliseEvent(line)
      for (const evt of events) {
        yield evt
      }
    }
  } catch (err) {
    yield {
      type: 'error',
      message: `Error reading stream: ${err.message}`
    }
  }

  // Wait for process exit
  await exitPromise

  if (exitCode !== 0 && exitCode !== null) {
    yield {
      type: 'error',
      message: `claude exited with code ${exitCode}`
    }
  }
}

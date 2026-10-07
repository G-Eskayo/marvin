import { spawn } from 'child_process'
import { createInterface } from 'readline'

// Normalise one line of JSONL output from `claude --output-format stream-json` into
// a consistent event shape. Tolerates non-JSON lines (logs, errors from subprocess).
export function parseStreamLine(line) {
  const trimmed = line.trim()
  if (!trimmed || trimmed[0] !== '{') {
    return null
  }

  let ev
  try {
    ev = JSON.parse(trimmed)
  } catch {
    return null
  }

  const type = ev.type

  // Session init: returns session_start event with the session ID.
  if (type === 'session_start') {
    return {
      type: 'session_start',
      sessionId: ev.session_id
    }
  }

  // Assistant message: text and/or tool_use blocks. Flatten into discrete events.
  if (type === 'assistant') {
    const content = ev.message?.content || []
    const events = []
    for (const block of content) {
      if (block.type === 'text') {
        events.push({
          type: 'text_delta',
          text: block.text || ''
        })
      } else if (block.type === 'tool_use') {
        events.push({
          type: 'tool_use',
          toolName: block.name,
          toolInput: block.input,
          toolId: block.id
        })
      }
    }
    return events.length > 0 ? events : null
  }

  // Streaming text delta.
  if (type === 'text_delta') {
    return {
      type: 'text_delta',
      text: ev.delta || ''
    }
  }

  // Tool use block (streaming).
  if (type === 'tool_use_start') {
    return {
      type: 'tool_use',
      toolName: ev.name,
      toolId: ev.id
    }
  }

  // Tool result.
  if (type === 'tool_result') {
    return {
      type: 'result',
      resultText: ev.result || '',
      resultError: ev.is_error ? true : false
    }
  }

  // Final message result with usage and metadata.
  if (type === 'result') {
    const usage = ev.usage || {}
    return {
      type: 'result',
      isError: ev.is_error || false,
      resultText: ev.result || '',
      numTurns: ev.num_turns || 0,
      durationMs: ev.duration_ms || 0,
      costUsd: ev.total_cost_usd || 0.0,
      inputTokens: usage.input_tokens || 0,
      outputTokens: usage.output_tokens || 0,
      cacheCreationTokens: usage.cache_creation_input_tokens || 0,
      cacheReadTokens: usage.cache_read_input_tokens || 0
    }
  }

  // Error event.
  if (type === 'error') {
    return {
      type: 'error',
      message: ev.message || 'Unknown error'
    }
  }

  // Unknown event type; skip it.
  return null
}

// Run a headless claude session with resume support. Returns events and final session ID.
// options: { message, sessionId?, claudeBin, spawnFn?, createInterfaceFn? }
// - message: the user message to send
// - sessionId: optional session ID to resume (--resume flag)
// - claudeBin: path to claude binary
// - spawnFn: injected spawn function for testing (defaults to child_process.spawn)
// - createInterfaceFn: injected readline interface creator for testing (defaults to createInterface)
// Returns { events, sessionId } where events is an array of normalised stream events.
export async function runSession({ message, sessionId, claudeBin, spawnFn = spawn, createInterfaceFn = createInterface }) {
  const args = [
    '-p',
    message,
    '--output-format', 'stream-json',
    '--verbose',
    '--include-partial-messages',
    '--permission-prompts', 'none'
  ]

  if (sessionId) {
    args.push('--resume', sessionId)
  }

  const proc = spawnFn(claudeBin, args)

  if (!proc.stdout) {
    throw new Error('Failed to spawn claude process: no stdout')
  }

  const rl = createInterfaceFn({
    input: proc.stdout,
    crlfDelay: Infinity
  })

  let currentSessionId = sessionId
  const events = []
  let processError = null
  let exitCode = null
  let closed = false

  return new Promise((resolve, reject) => {
    rl.on('line', (line) => {
      const parsed = parseStreamLine(line)

      if (parsed === null) {
        return
      }

      if (Array.isArray(parsed)) {
        for (const event of parsed) {
          if (event.type === 'session_start' && !currentSessionId) {
            currentSessionId = event.sessionId
          }
          events.push(event)
        }
      } else {
        if (parsed.type === 'session_start' && !currentSessionId) {
          currentSessionId = parsed.sessionId
        }
        events.push(parsed)
      }
    })

    rl.on('close', () => {
      closed = true
      if (processError) {
        reject(processError)
      } else if (exitCode !== 0 && exitCode !== null) {
        reject(new Error(`claude exited with code ${exitCode}`))
      } else {
        resolve({ events, sessionId: currentSessionId })
      }
    })

    rl.on('error', (err) => {
      reject(err)
    })

    proc.on('error', (err) => {
      processError = err
      if (!closed) {
        rl.close()
      }
    })

    proc.on('exit', (code) => {
      exitCode = code
      if (!closed) {
        rl.close()
      }
    })
  })
}

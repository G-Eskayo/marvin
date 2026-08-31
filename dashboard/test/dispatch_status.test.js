import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { readDispatchStatus } from '../electron/main/dispatch_status.js'

function withTempFile(content, fn) {
  const dir = mkdtempSync(path.join(tmpdir(), 'dispatch-status-test-'))
  const filePath = path.join(dir, 'dispatch-state.json')
  if (content !== undefined) writeFileSync(filePath, content)
  try {
    return fn(filePath)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe('readDispatchStatus', () => {
  it('is idle when the state file does not exist', () => {
    withTempFile(undefined, (filePath) => {
      expect(readDispatchStatus(filePath)).toEqual({ busy: false, task: null, startedAt: null })
    })
  })

  it('is idle when the state file says busy: false', () => {
    withTempFile(JSON.stringify({ busy: false }), (filePath) => {
      expect(readDispatchStatus(filePath)).toEqual({ busy: false, task: null, startedAt: null })
    })
  })

  it('is idle when the state file is corrupt', () => {
    withTempFile('not json', (filePath) => {
      expect(readDispatchStatus(filePath)).toEqual({ busy: false, task: null, startedAt: null })
    })
  })

  it('reports the task and start time when busy', () => {
    withTempFile(
      JSON.stringify({ busy: true, task: 'ticket #28: Hard/ambiguous bench task design', task_id: 'abc', started_at: '2026-08-31T20:04:46.468862+00:00' }),
      (filePath) => {
        expect(readDispatchStatus(filePath)).toEqual({
          busy: true,
          task: 'ticket #28: Hard/ambiguous bench task design',
          startedAt: '2026-08-31T20:04:46.468862+00:00'
        })
      }
    )
  })

  it('falls back to a null task if busy but the field is missing', () => {
    withTempFile(JSON.stringify({ busy: true, started_at: '2026-08-31T20:04:46+00:00' }), (filePath) => {
      const result = readDispatchStatus(filePath)
      expect(result.busy).toBe(true)
      expect(result.task).toBeNull()
    })
  })
})

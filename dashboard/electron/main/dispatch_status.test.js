import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import fs from 'fs'
import path from 'path'
import os from 'os'
import { readDispatchStatus } from './dispatch_status.js'

describe('dispatch_status', () => {
  let tmpDir

  beforeEach(() => {
    // Create a temporary directory for test files
    tmpDir = path.join(os.tmpdir(), `dispatch-test-${Date.now()}`)
    if (!fs.existsSync(tmpDir)) {
      fs.mkdirSync(tmpDir, { recursive: true })
    }
  })

  afterEach(() => {
    // Clean up test files
    if (fs.existsSync(tmpDir)) {
      fs.rmSync(tmpDir, { recursive: true, force: true })
    }
  })

  it('returns busy=false when no state file exists', () => {
    const result = readDispatchStatus(path.join(tmpDir, 'nonexistent.json'))
    expect(result.busy).toBe(false)
    expect(result.task).toBeNull()
    expect(result.startedAt).toBeNull()
  })

  it('returns busy=false when state file says busy=false', () => {
    const statePath = path.join(tmpDir, 'state.json')
    fs.writeFileSync(statePath, JSON.stringify({ busy: false }))

    const result = readDispatchStatus(statePath)
    expect(result.busy).toBe(false)
    expect(result.task).toBeNull()
  })

  it('returns busy=true with task info when state file says busy=true', () => {
    const statePath = path.join(tmpDir, 'state.json')
    fs.writeFileSync(statePath, JSON.stringify({
      busy: true,
      task: 'test task',
      task_id: 'task123',
      started_at: '2026-10-07T10:00:00Z'
    }))

    const result = readDispatchStatus(statePath)
    expect(result.busy).toBe(true)
    expect(result.task).toBe('test task')
    expect(result.startedAt).toBe('2026-10-07T10:00:00Z')
  })

  it('cross-checks pid liveness when task_id is present', () => {
    const statePath = path.join(tmpDir, 'state.json')
    const tasksDir = path.join(tmpDir, 'tasks')
    fs.mkdirSync(tasksDir, { recursive: true })

    // Create state file saying busy with a task
    fs.writeFileSync(statePath, JSON.stringify({
      busy: true,
      task: 'test task',
      task_id: 'task123',
      started_at: '2026-10-07T10:00:00Z'
    }))

    // Create task record with a dead PID (very high number unlikely to exist)
    const deadPid = 999999999
    const taskRecordPath = path.join(tasksDir, 'task123.json')
    fs.writeFileSync(taskRecordPath, JSON.stringify({
      task_id: 'task123',
      pid: deadPid
    }))

    // Mock process.kill to return "ESRCH" (no such process)
    const originalKill = process.kill
    process.kill = vi.fn(() => {
      throw new Error('ESRCH: no such process')
    })

    try {
      const result = readDispatchStatus(statePath, tasksDir)
      // Dead PID should cause busy to be false
      expect(result.busy).toBe(false)
    } finally {
      process.kill = originalKill
    }
  })

  it('handles missing task record gracefully', () => {
    const statePath = path.join(tmpDir, 'state.json')
    const tasksDir = path.join(tmpDir, 'tasks')
    fs.mkdirSync(tasksDir, { recursive: true })

    fs.writeFileSync(statePath, JSON.stringify({
      busy: true,
      task: 'test task',
      task_id: 'task123',
      started_at: '2026-10-07T10:00:00Z'
    }))

    // Don't create the task record file — it should be treated as if the pid is alive
    // (we can't verify, so we trust the state file)
    const result = readDispatchStatus(statePath, tasksDir)
    expect(result.busy).toBe(true)
  })

  it('returns null for missing started_at field', () => {
    const statePath = path.join(tmpDir, 'state.json')
    fs.writeFileSync(statePath, JSON.stringify({
      busy: true,
      task: 'test task'
      // no started_at field
    }))

    const result = readDispatchStatus(statePath)
    expect(result.busy).toBe(true)
    expect(result.startedAt).toBeNull()
  })
})

import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { listJobs } from '../electron/main/jobs.js'

const NOW = Date.parse('2026-10-05T12:00:00Z')
const ago = (min) => new Date(NOW - min * 60_000).toISOString()
const withDir = (fn) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'jobs-'))
  try {
    return fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}
const put = (dir, job, runs, label = job) => writeFileSync(path.join(dir, `${job}.json`), JSON.stringify({ job, label, runs }))
const run = (over = {}) => ({ id: 'r', status: 'passed', started_at: ago(10), finished_at: ago(9), steps: [], summary: '', error: '', ...over })

describe('listJobs', () => {
  it('reports a running job with its current step and when it started', () =>
    withDir((dir) => {
      put(dir, 'cat', [run({ status: 'running', finished_at: null, started_at: ago(1), steps: [{ step: 'GitHub repos', detail: '18 found', at: ago(1) }, { step: 'Local folders', detail: '', at: ago(0.5) }] })])
      const [j] = listJobs({ dir, now: NOW })
      expect(j.status).toBe('running')
      expect(j.current).toMatchObject({ step: 'Local folders' })
      expect(j.current.startedAt).toBe(ago(1))
    }))

  it('reports idle with the last run summary and duration, failed with the error', () =>
    withDir((dir) => {
      put(dir, 'a', [run({ started_at: ago(10), finished_at: ago(9.5), summary: '30 projects' })])
      put(dir, 'b', [run({ status: 'failed', error: 'offline' })])
      const jobs = Object.fromEntries(listJobs({ dir, now: NOW }).map((j) => [j.job, j]))
      expect(jobs.a).toMatchObject({ status: 'idle', last: { summary: '30 projects', durationS: 30 } })
      expect(jobs.b).toMatchObject({ status: 'failed', last: { error: 'offline' } })
    }))

  it('flags a run that started long ago and never finished as crashed, not running', () =>
    withDir((dir) => {
      put(dir, 'x', [run({ status: 'running', finished_at: null, started_at: ago(120) })])
      expect(listJobs({ dir, now: NOW })[0].status).toBe('crashed')
    }))

  it('orders running first, then problems, then the most recently active', () =>
    withDir((dir) => {
      put(dir, 'old', [run({ started_at: ago(500), finished_at: ago(499) })])
      put(dir, 'new', [run({ started_at: ago(5), finished_at: ago(4) })])
      put(dir, 'bad', [run({ status: 'failed', started_at: ago(300), finished_at: ago(299) })])
      put(dir, 'live', [run({ status: 'running', finished_at: null, started_at: ago(1) })])
      expect(listJobs({ dir, now: NOW }).map((j) => j.job)).toEqual(['live', 'bad', 'new', 'old'])
    }))

  it('keeps recent runs (newest first, capped) with their steps for the drill-down', () =>
    withDir((dir) => {
      put(dir, 'h', Array.from({ length: 12 }, (_, i) => run({ id: `r${i}`, started_at: ago(100 - i), finished_at: ago(99 - i), steps: [{ step: 's', detail: String(i), at: ago(99 - i) }] })))
      const [j] = listJobs({ dir, now: NOW })
      expect(j.runs.length).toBe(8)
      expect(j.runs[0].id).toBe('r11')
      expect(j.runs[0].steps[0].detail).toBe('11')
    }))

  it('ignores lock/tmp files, corrupt files and a missing directory', () =>
    withDir((dir) => {
      writeFileSync(path.join(dir, '.x.lock'), '')
      writeFileSync(path.join(dir, 'x.tmp'), '{}')
      writeFileSync(path.join(dir, 'bad.json'), '{nope')
      expect(listJobs({ dir, now: NOW })).toEqual([])
      expect(listJobs({ dir: path.join(dir, 'missing'), now: NOW })).toEqual([])
    }))
})

import { describe, it, expect, vi } from 'vitest'
import { runMasterBuild } from '../electron/main/docs_handlers.js'

describe('runMasterBuild', () => {
  it('returns { ok: true } on success and calls exec with [script, --dry-run]', async () => {
    const exec = vi.fn(async () => undefined)
    const result = await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py' })
    expect(result).toEqual({ ok: true })
    expect(exec).toHaveBeenCalledWith('/usr/bin/python3', ['/path/to/tidy_agent.py', '--dry-run'], { timeout: 300_000 })
  })

  it('returns { ok: false, output } on generator failure with multi-line Python traceback', async () => {
    const stderr = 'Traceback (most recent call last):\n  File "tidy_agent.py", line 42, in run\n    raise ValueError("Desktop folder not found")\nValueError: Desktop folder not found'
    const exec = vi.fn(async () => { throw new Error('Command failed') })
    exec.mockRejectedValue({ stderr })

    const result = await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py' })
    expect(result.ok).toBe(false)
    expect(result.output).toBe('ValueError: Desktop folder not found')
    expect(result.output).not.toContain('\n')
  })

  it('returns one plain line from .message when exec has no stderr (permission error)', async () => {
    const error = new Error('EACCES: permission denied, open /home/.claude/organize/tidy_agent.py')
    error.code = 'EACCES'
    error.stderr = null

    const exec = vi.fn(async () => { throw error })
    const result = await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py' })
    expect(result.ok).toBe(false)
    expect(result.output).toBe('EACCES: permission denied, open /home/.claude/organize/tidy_agent.py')
    expect(result.output).not.toContain('\n')
  })

  it('returns a single bounded line even with huge multi-thousand-line stderr', async () => {
    const lines = Array(5000).fill('Line of output from a huge log\n')
    const stderr = lines.join('')

    const exec = vi.fn(async () => { throw new Error('Command failed') })
    exec.mockRejectedValue({ stderr })

    const result = await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py' })
    expect(result.ok).toBe(false)
    expect(result.output).toEqual('Line of output from a huge log')
    expect(result.output.split('\n')).toHaveLength(1)
  })

  it('resolves with one-line message on timeout/SIGTERM', async () => {
    const error = new Error('The operation was aborted')
    error.signal = 'SIGTERM'
    error.stderr = ''

    const exec = vi.fn(async () => { throw error })
    const result = await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py' })
    expect(result.ok).toBe(false)
    expect(result.output).toBe('The operation was aborted')
    expect(result.output).not.toContain('\n')
  })

  it('passes the given timeout and maxBuffer options through to exec unchanged', async () => {
    const exec = vi.fn(async () => undefined)
    const timeout = 500_000
    const maxBuffer = 2 * 1024 * 1024

    await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py', timeout, maxBuffer })

    expect(exec).toHaveBeenCalledWith('/usr/bin/python3', ['/path/to/tidy_agent.py', '--dry-run'], { timeout, maxBuffer })
  })

  it('uses the default 300s timeout when not specified', async () => {
    const exec = vi.fn(async () => undefined)
    await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py' })
    expect(exec).toHaveBeenCalledWith(
      '/usr/bin/python3',
      ['/path/to/tidy_agent.py', '--dry-run'],
      expect.objectContaining({ timeout: 300_000 })
    )
  })

  it('returns "unknown error" when error has no stderr or message', async () => {
    const exec = vi.fn(async () => { throw {} })
    const result = await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py' })
    expect(result.ok).toBe(false)
    expect(result.output).toBe('unknown error')
  })

  it('skips empty lines and returns the last non-blank line', async () => {
    const stderr = 'Error line 1\nError line 2\n\n\n'
    const exec = vi.fn(async () => { throw new Error('Command failed') })
    exec.mockRejectedValue({ stderr })

    const result = await runMasterBuild({ exec, python: '/usr/bin/python3', script: '/path/to/tidy_agent.py' })
    expect(result.ok).toBe(false)
    expect(result.output).toBe('Error line 2')
  })
})

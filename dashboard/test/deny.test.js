import { describe, it, expect, vi } from 'vitest'
import { formatFeedback, sendFeedback, dropEntirely } from '../webhook-server/deny.js'

const PR_URL = 'https://github.com/G-Eskayo/marvin/pull/71'

function execReturning(stdout) {
  return vi.fn().mockResolvedValue({ stdout, stderr: '' })
}

describe('formatFeedback', () => {
  it('lists selected reasons and appends the free-text comment', () => {
    const feedback = formatFeedback(['Insufficient tests', 'Evidence missing'], 'also missing a screenshot')
    expect(feedback).toContain('- Insufficient tests')
    expect(feedback).toContain('- Evidence missing')
    expect(feedback).toContain('also missing a screenshot')
  })

  it('omits the Reasons section when nothing was selected', () => {
    expect(formatFeedback([], '')).not.toContain('Reasons:')
  })

  it('handles missing reasons/comment without throwing', () => {
    expect(() => formatFeedback()).not.toThrow()
  })
})

describe('sendFeedback', () => {
  it('rejects a non-GitHub URL without calling exec', async () => {
    const exec = vi.fn()
    await expect(sendFeedback({ prUrl: 'not-a-url', ticketNumber: 42 }, exec)).rejects.toThrow('Not a GitHub PR URL')
    expect(exec).not.toHaveBeenCalled()
  })

  it('comments on the PR and ticket, releases the claim, and tags for re-engagement', async () => {
    const exec = vi.fn().mockImplementation((cmd, args) => {
      if (args[0] === 'issue' && args[1] === 'view') {
        return Promise.resolve({ stdout: JSON.stringify({ labels: [{ name: 'claimed:mac-mini' }, { name: 'ready-for-agent' }] }) })
      }
      return Promise.resolve({ stdout: '', stderr: '' })
    })

    await sendFeedback({ prUrl: PR_URL, ticketNumber: 42, reasons: ['Insufficient tests'], comment: '' }, exec)

    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'comment', PR_URL, '--body', expect.stringContaining('Insufficient tests')])
    expect(exec).toHaveBeenCalledWith('gh', ['issue', 'comment', '42', '--repo', 'G-Eskayo/marvin', '--body', expect.stringContaining('Insufficient tests')])
    expect(exec).toHaveBeenCalledWith('gh', ['issue', 'edit', '42', '--repo', 'G-Eskayo/marvin', '--remove-label', 'claimed:mac-mini'])
    expect(exec).toHaveBeenCalledWith('gh', ['issue', 'edit', '42', '--repo', 'G-Eskayo/marvin', '--add-label', 'needs-reengagement'])
  })

  it('creates the needs-reengagement label on first use, then retries the add', async () => {
    let addLabelAttempts = 0
    const exec = vi.fn().mockImplementation((cmd, args) => {
      if (args[0] === 'issue' && args[1] === 'view') {
        return Promise.resolve({ stdout: JSON.stringify({ labels: [] }) })
      }
      if (args[0] === 'issue' && args[1] === 'edit' && args.includes('--add-label')) {
        addLabelAttempts += 1
        if (addLabelAttempts === 1) {
          return Promise.reject(new Error("gh: label 'needs-reengagement' not found"))
        }
      }
      return Promise.resolve({ stdout: '', stderr: '' })
    })

    await sendFeedback({ prUrl: PR_URL, ticketNumber: 42, reasons: [], comment: 'looks off' }, exec)

    expect(addLabelAttempts).toBe(2)
    expect(exec).toHaveBeenCalledWith('gh', ['label', 'create', 'needs-reengagement', '--repo', 'G-Eskayo/marvin'])
  })

  it('skips ticket-scoped calls when there is no linked ticket', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    await sendFeedback({ prUrl: PR_URL, ticketNumber: null, reasons: [], comment: '' }, exec)
    expect(exec).toHaveBeenCalledTimes(1)
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'comment', PR_URL, '--body', expect.any(String)])
  })
})

describe('dropEntirely', () => {
  it('rejects a non-GitHub URL without calling exec', async () => {
    const exec = vi.fn()
    await expect(dropEntirely({ prUrl: 'not-a-url', ticketNumber: 42 }, exec)).rejects.toThrow('Not a GitHub PR URL')
    expect(exec).not.toHaveBeenCalled()
  })

  it('closes the PR and ticket and releases the claim, with no comment posted', async () => {
    const exec = execReturning(JSON.stringify({ labels: [{ name: 'claimed:macbook-pro' }] }))
    await dropEntirely({ prUrl: PR_URL, ticketNumber: 42 }, exec)

    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'close', PR_URL])
    expect(exec).toHaveBeenCalledWith('gh', ['issue', 'close', '42', '--repo', 'G-Eskayo/marvin'])
    expect(exec).toHaveBeenCalledWith('gh', ['issue', 'edit', '42', '--repo', 'G-Eskayo/marvin', '--remove-label', 'claimed:macbook-pro'])
    expect(exec).not.toHaveBeenCalledWith('gh', expect.arrayContaining(['comment']))
  })

  it('skips ticket-scoped calls when there is no linked ticket', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    await dropEntirely({ prUrl: PR_URL, ticketNumber: null }, exec)
    expect(exec).toHaveBeenCalledTimes(1)
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'close', PR_URL])
  })
})

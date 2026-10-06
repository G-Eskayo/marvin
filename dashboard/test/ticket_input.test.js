import { describe, it, expect, vi } from 'vitest'
import { planInput, HUMAN_INPUT_MARKER } from '../src/lib/ticket_input.js'
import { postTicketInput } from '../electron/main/ticket_input.js'

describe('planInput: what leaving a comment does to a ticket', () => {
  it('answers a needs-info ticket: back to ready, claim released', () => {
    const p = planInput(['needs-info', 'claimed:mac-mini', 'enhancement'], 'OPEN')
    expect(p).toMatchObject({ requeue: true, add: ['ready-for-agent'], remove: ['needs-info', 'claimed:mac-mini'] })
    expect(p.effect).toMatch(/back to ready/i)
  })

  it('un-parks a ticket the pipeline gave up on (claimed, no longer ready-for-agent)', () => {
    const p = planInput(['claimed:macbook-pro', 'enhancement'], 'OPEN')
    expect(p).toMatchObject({ requeue: true, add: ['ready-for-agent'], remove: ['claimed:macbook-pro'] })
  })

  it('leaves a ticket that is already queued, or being rebuilt, or yours, or closed alone: comment only', () => {
    for (const [labels, state] of [
      [['ready-for-agent'], 'OPEN'],
      [['ready-for-agent', 'claimed:mac-mini'], 'OPEN'],
      [['needs-reengagement', 'ready-for-agent', 'claimed:mac-mini'], 'OPEN'],
      [['ready-for-human'], 'OPEN'],
      [['wontfix'], 'OPEN'],
      [['needs-info'], 'CLOSED']
    ]) {
      const p = planInput(labels, state)
      expect(p.requeue, JSON.stringify(labels)).toBe(false)
      expect(p.add).toEqual([])
      expect(p.remove).toEqual([])
      expect(p.effect.length).toBeGreaterThan(10)
    }
  })
})

const fakeGh = (labels, state = 'OPEN', failOn = null) => {
  const calls = []
  const exec = vi.fn(async (cmd, args) => {
    calls.push(args)
    if (failOn && args.join(' ').includes(failOn)) throw new Error('gh failed')
    if (args[0] === 'issue' && args[1] === 'view') return { stdout: JSON.stringify({ labels: labels.map((name) => ({ name })), state }) }
    return { stdout: '' }
  })
  return { exec, calls }
}

describe('postTicketInput', () => {
  it('posts the comment with the marker, then re-queues a waiting ticket', async () => {
    const { exec, calls } = fakeGh(['needs-info'])
    const r = await postTicketInput({ repo: 'G-Eskayo/marvin', number: 12, body: 'Use option B' }, exec)
    expect(r).toMatchObject({ posted: true, requeued: true })
    const comment = calls.find((a) => a[1] === 'comment')
    expect(comment).toContain('G-Eskayo/marvin')
    expect(comment[comment.indexOf('--body') + 1]).toContain('Use option B')
    expect(comment[comment.indexOf('--body') + 1]).toContain(HUMAN_INPUT_MARKER)
    const edit = calls.find((a) => a[1] === 'edit')
    expect(edit).toEqual(expect.arrayContaining(['--add-label', 'ready-for-agent', '--remove-label', 'needs-info']))
  })

  it('comments the ticket first, so a failed label change never loses the answer', async () => {
    const { exec, calls } = fakeGh(['needs-info'], 'OPEN', 'edit')
    const r = await postTicketInput({ repo: 'G-Eskayo/marvin', number: 12, body: 'Use option B' }, exec)
    expect(r).toMatchObject({ posted: true, requeued: false })
    expect(r.warning).toMatch(/could not be moved back to ready/i)
    expect(calls.some((a) => a[1] === 'comment')).toBe(true)
  })

  it('does not touch labels on a ticket that is not waiting', async () => {
    const { exec, calls } = fakeGh(['ready-for-agent'])
    const r = await postTicketInput({ repo: 'G-Eskayo/marvin', number: 12, body: 'FYI' }, exec)
    expect(r).toMatchObject({ posted: true, requeued: false })
    expect(calls.some((a) => a[1] === 'edit')).toBe(false)
  })

  it('refuses empty comments and non-GitHub-owner repos without calling gh', async () => {
    const { exec } = fakeGh([])
    await expect(postTicketInput({ repo: 'G-Eskayo/marvin', number: 12, body: '   ' }, exec)).rejects.toThrow(/empty/i)
    await expect(postTicketInput({ repo: 'someone/else', number: 12, body: 'x' }, exec)).rejects.toThrow(/repo/i)
    await expect(postTicketInput({ repo: 'G-Eskayo/marvin', number: 'abc', body: 'x' }, exec)).rejects.toThrow(/ticket number/i)
    expect(exec).not.toHaveBeenCalled()
  })
})

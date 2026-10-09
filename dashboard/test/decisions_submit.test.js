import { describe, it, expect, vi } from 'vitest'
import { submitDecisions, sendBackForOptions, validateAnswers, OPTIONS_REQUEST } from '../electron/main/decisions_submit.js'
import { parseDecisions } from '../webhook-server/decisions.js'

const BODY = `Images above.

## Decisions
<!-- marvin:decisions -->
### dance: Which launch animation?
- [ ] A: Clap & wiggle
- [ ] B: Balance a bubble

### handoff: Hand-off
- [ ] Glide
- [ ] Dive

### character: Changes? (text) (optional)
`

// A fake gh: answers the issue read, records PATCH bodies (read from the --input file) and comments.
function fakeGh({ body = BODY, labels = [], pullRequest = true, failPatch = false, failComment = false } = {}) {
  const state = { patched: null, comments: [], labelEdits: [] }
  const exec = vi.fn(async (cmd, args) => {
    if (args[0] === 'api' && args[1] === '-X' && args[2] === 'PATCH') {
      if (failPatch) throw Object.assign(new Error('Command failed'), { stderr: 'HTTP 502' })
      const { readFileSync } = await import('fs')
      state.patched = JSON.parse(readFileSync(args[args.indexOf('--input') + 1], 'utf8')).body
      return { stdout: '{}' }
    }
    if (args[0] === 'api' && /\/comments$/.test(args[1])) {
      if (failComment) throw Object.assign(new Error('Command failed'), { stderr: 'HTTP 500: comment failed' })
      state.comments.push(args[args.indexOf('-f') + 1].slice('body='.length))
      return { stdout: 'https://github.com/o/r/pull/9#issuecomment-1\n' }
    }
    if (args[0] === 'api') {
      return { stdout: JSON.stringify({ body, labels: labels.map((name) => ({ name })), ...(pullRequest ? { pull_request: {} } : {}) }) }
    }
    if (args[0] === 'issue' && args[1] === 'edit') { state.labelEdits.push(args); return { stdout: '' } }
    if (args[0] === 'pr' && args[1] === 'comment') { state.comments.push(args[args.indexOf('--body') + 1]); return { stdout: '' } }
    throw new Error(`unexpected gh ${args.join(' ')}`)
  })
  return { exec, state }
}

describe('submitDecisions', () => {
  it('writes the answers into the description first, then posts the record comment', async () => {
    const { exec, state } = fakeGh()
    const r = await submitDecisions({ repo: 'G-Eskayo/clarity-captions', number: 99, answers: { dance: { choices: ['B: Balance a bubble'], note: 'cute' }, handoff: { choices: ['Dive'] } } }, { exec })
    expect(r).toMatchObject({ ok: true, pending: [], commentUrl: 'https://github.com/o/r/pull/9#issuecomment-1' })
    expect(state.patched).toContain('- [x] B: Balance a bubble')
    expect(state.patched).toContain('- [x] Dive')
    expect(state.patched).toContain('> **Note:** cute')
    expect(state.comments[0]).toContain('Decisions from the owner')
    const order = exec.mock.calls.map((c) => (c[1][2] === 'PATCH' ? 'patch' : /comments$/.test(c[1][1]) ? 'comment' : 'other'))
    expect(order.indexOf('patch')).toBeLessThan(order.indexOf('comment'))
  })

  it('reports what is still pending after a partial answer', async () => {
    const { exec } = fakeGh()
    const r = await submitDecisions({ repo: 'o/r', number: 9, answers: { dance: { choices: ['A: Clap & wiggle'] } } }, { exec })
    expect(r.pending).toEqual(['handoff'])
  })

  it('posts nothing when nothing changed', async () => {
    const { exec, state } = fakeGh({ body: BODY.replace('- [ ] Glide', '- [x] Glide') })
    const r = await submitDecisions({ repo: 'o/r', number: 9, answers: { handoff: { choices: ['Glide'] } } }, { exec })
    expect(r.unchanged).toBe(true)
    expect(state.patched).toBeNull()
    expect(state.comments).toHaveLength(0)
  })

  it('a failed edit writes nothing else (no comment claiming answers that were not saved)', async () => {
    const { exec, state } = fakeGh({ failPatch: true })
    await expect(submitDecisions({ repo: 'o/r', number: 9, answers: { handoff: { choices: ['Glide'] } } }, { exec })).rejects.toThrow()
    expect(state.comments).toHaveLength(0)
  })

  it('a failed comment keeps the saved answers and says so', async () => {
    const { exec, state } = fakeGh({ failComment: true })
    const r = await submitDecisions({ repo: 'o/r', number: 9, answers: { handoff: { choices: ['Glide'] } } }, { exec })
    expect(state.patched).toContain('- [x] Glide')
    expect(r.ok).toBe(true)
    expect(r.commentError).toMatch(/answers saved in the description/)
  })

  it('a ticket waiting on decisions moves from needs-info to ready-for-agent once all required are answered', async () => {
    const { exec, state } = fakeGh({ labels: ['needs-info', 'priority:p1'], pullRequest: false })
    const r = await submitDecisions({ repo: 'o/r', number: 5, answers: { dance: { choices: ['A: Clap & wiggle'] }, handoff: { choices: ['Glide'] } } }, { exec })
    expect(r.labelsChanged).toBe(true)
    expect(state.labelEdits[0]).toEqual(expect.arrayContaining(['--remove-label', 'needs-info', '--add-label', 'ready-for-agent']))
  })

  it('does not touch labels while required decisions remain, or on a PR', async () => {
    const t = fakeGh({ labels: ['needs-info'], pullRequest: false })
    await submitDecisions({ repo: 'o/r', number: 5, answers: { dance: { choices: ['A: Clap & wiggle'] } } }, { exec: t.exec })
    expect(t.state.labelEdits).toHaveLength(0)
    const p = fakeGh({ labels: ['needs-info'] })
    await submitDecisions({ repo: 'o/r', number: 5, answers: { dance: { choices: ['A: Clap & wiggle'] }, handoff: { choices: ['Glide'] } } }, { exec: p.exec })
    expect(p.state.labelEdits).toHaveLength(0)
  })

  it('refuses bad input: repo, number, unknown questions or options, two answers to a one-answer question', async () => {
    const { exec } = fakeGh()
    await expect(submitDecisions({ repo: 'not a repo', number: 9, answers: {} }, { exec })).rejects.toThrow(/not a repository/)
    await expect(submitDecisions({ repo: 'o/r', number: -1, answers: {} }, { exec })).rejects.toThrow(/not an issue or PR number/)
    await expect(submitDecisions({ repo: 'o/r', number: 9, answers: { nope: { choices: ['x'] } } }, { exec })).rejects.toThrow(/not a question/)
    await expect(submitDecisions({ repo: 'o/r', number: 9, answers: { handoff: { choices: ['Fly'] } } }, { exec })).rejects.toThrow(/not an option/)
    await expect(submitDecisions({ repo: 'o/r', number: 9, answers: { handoff: { choices: ['Glide', 'Dive'] } } }, { exec })).rejects.toThrow(/one answer/)
    await expect(submitDecisions({ repo: 'o/r', number: 9, answers: { character: { choices: ['x'] } } }, { exec })).rejects.toThrow(/written answer/)
  })

  it('refuses when the description no longer has a decisions section', async () => {
    const { exec } = fakeGh({ body: 'rewritten' })
    await expect(submitDecisions({ repo: 'o/r', number: 9, answers: {} }, { exec })).rejects.toThrow(/no Decisions section/)
  })

  it('validateAnswers rejects a non-object', () => {
    expect(() => validateAnswers(parseDecisions(BODY), null)).toThrow(/no answers/)
  })
})

describe('sendBackForOptions', () => {
  it('a pipeline PR goes back to its ticket through the deny path, with the format in the message', async () => {
    const deny = vi.fn().mockResolvedValue({ ok: true })
    const r = await sendBackForOptions({ prUrl: 'https://github.com/o/r/pull/9', ticketNumber: 12, reasons: ['"## Choose" asks'] }, { exec: vi.fn(), deny })
    expect(r.sentBack).toBe(true)
    expect(deny).toHaveBeenCalledWith(expect.objectContaining({ ticketNumber: 12, action: 'feedback', comment: expect.stringContaining('<!-- marvin:decisions -->') }))
  })

  it('a hand-made PR gets the request as a comment', async () => {
    const { exec, state } = fakeGh()
    const r = await sendBackForOptions({ prUrl: 'https://github.com/o/r/pull/9', ticketNumber: null, reasons: [] }, { exec, deny: vi.fn() })
    expect(r).toEqual({ sentBack: false, commented: true })
    expect(state.comments[0]).toBe(OPTIONS_REQUEST([]))
  })
})

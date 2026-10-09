import { describe, it, expect, vi } from 'vitest'

vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))
vi.mock('../webhook-server/failure_log.js', () => ({ recordFailure: vi.fn() }))
vi.mock('../webhook-server/rebase_status.js', () => ({ writeRebaseStatus: vi.fn(), readRebaseStatus: vi.fn(() => ({})) }))

import { mergePr } from '../webhook-server/merge.js'
import { describePrState } from '../src/lib/prState.js'
import {
  parseDecisions, pendingDecisions, summarizeDecisions, vagueness, applyAnswers, decisionsComment, isAnswered
} from '../webhook-server/decisions.js'
import { assertDecisions } from '../webhook-server/decisions_gate.js'

// The owner's rule (2026-10-09): a PR or ticket that asks him to choose must give him options to answer, and can't be
// approved until the required ones are answered; asking in prose is "too vague".

const SEAL = `Intro text with images.

## Decisions
<!-- marvin:decisions -->
### dance: Which launch animation?
- [ ] A: Clap & wiggle
- [ ] B: Balance a bubble
- [ ] C: Belly slide & wave

### mix: Mix parts of several? (pick any) (optional)
- [ ] A's clap
- [ ] B's bubble
- [ ] C's slide

### handoff: Hand-off into the start screen
- [ ] Glide
- [ ] Dive

### character: Any changes to the character? (text) (optional)

## Original notes
- [ ] not a decision
`

describe('parseDecisions', () => {
  it('reads ids, questions, kinds, required and options', () => {
    const d = parseDecisions(SEAL)
    expect(d.present).toBe(true)
    expect(d.problems).toEqual([])
    expect(d.questions.map((q) => [q.id, q.kind, q.required, q.options.length])).toEqual([
      ['dance', 'single', true, 3], ['mix', 'multi', false, 3], ['handoff', 'single', true, 2], ['character', 'text', false, 0]
    ])
    expect(d.questions[0].question).toBe('Which launch animation?')
    expect(d.questions[1].question).toBe('Mix parts of several?')
  })

  it('stops at the next ## heading, so later checklists are not options', () => {
    const d = parseDecisions(SEAL)
    expect(d.questions.flatMap((q) => q.options.map((o) => o.label))).not.toContain('not a decision')
  })

  it('reads the answered state: ticked boxes, Answer and Note lines', () => {
    const body = SEAL.replace('- [ ] B: Balance', '- [x] B: Balance').replace('### character: Any changes to the character? (text) (optional)\n',
      '### character: Any changes to the character? (text) (optional)\n> **Answer:** bigger eyes\n')
      .replace('- [ ] Dive\n', '- [ ] Dive\n> **Note:** whichever is calmer\n')
    const d = parseDecisions(body)
    const by = Object.fromEntries(d.questions.map((q) => [q.id, q]))
    expect(by.dance.options.find((o) => o.checked).label).toBe('B: Balance a bubble')
    expect(by.character.answer).toBe('bigger eyes')
    expect(by.handoff.note).toBe('whichever is calmer')
  })

  it('has no section without the marker, even with a "## Decisions" heading', () => {
    expect(parseDecisions('## Decisions\n### a: b\n- [ ] x\n- [ ] y').present).toBe(false)
  })

  it('ignores a decisions block shown inside a code fence (docs, examples)', () => {
    const body = 'How to write one:\n```\n<!-- marvin:decisions -->\n### a: Pick?\n- [ ] x\n- [ ] y\n```\n'
    expect(parseDecisions(body).present).toBe(false)
    expect(vagueness(body)).toBeNull()
  })

  it('flags malformed questions: no id, duplicate ids, too few options, several ticked on a single choice, empty section', () => {
    const body = `<!-- marvin:decisions -->
### Which one?
- [ ] a
- [ ] b
### x: First
- [ ] only
### x: Again
- [x] a
- [x] b`
    const d = parseDecisions(body)
    expect(d.problems.join(' | ')).toMatch(/needs an id/)
    expect(d.problems.join(' | ')).toMatch(/"x" is used twice/)
    expect(d.problems.join(' | ')).toMatch(/offers 1 option/)
    expect(d.problems.join(' | ')).toMatch(/several ticked/)
    expect(parseDecisions('<!-- marvin:decisions -->\nnothing').problems).toContain('the decisions section has no questions')
  })

  it('accepts * bullets, X ticks, and flags in any order', () => {
    const d = parseDecisions('<!-- marvin:decisions -->\n### q1: Pick (optional) (pick any)\n* [X] a\n* [ ] b')
    expect(d.questions[0]).toMatchObject({ kind: 'multi', required: false })
    expect(d.questions[0].options[0].checked).toBe(true)
  })

  it('survives junk: null, numbers, a huge body', () => {
    expect(parseDecisions(null).present).toBe(false)
    expect(parseDecisions(42).present).toBe(false)
    const huge = SEAL + 'x\n'.repeat(200000)
    expect(parseDecisions(huge).questions).toHaveLength(4)
  })
})

describe('pending decisions', () => {
  it('lists required questions not yet answered; optional ones never block', () => {
    expect(pendingDecisions(parseDecisions(SEAL))).toEqual(['dance', 'handoff'])
    const answered = SEAL.replace('- [ ] C: Belly', '- [x] C: Belly').replace('- [ ] Glide', '- [x] Glide')
    expect(pendingDecisions(parseDecisions(answered))).toEqual([])
  })

  it('a single choice with two ticks is not answered', () => {
    const two = SEAL.replace('- [ ] A: Clap', '- [x] A: Clap').replace('- [ ] B: Bal', '- [x] B: Bal')
    expect(pendingDecisions(parseDecisions(two))).toContain('dance')
  })

  it('a required text question needs a non-empty answer', () => {
    const body = '<!-- marvin:decisions -->\n### why: Why? (text)\n> **Answer:**   \n'
    expect(pendingDecisions(parseDecisions(body))).toEqual(['why'])
    expect(isAnswered({ kind: 'text', answer: 'because' })).toBe(true)
  })

  it('summarizeDecisions is null without a section', () => {
    expect(summarizeDecisions('plain body')).toBeNull()
    expect(summarizeDecisions(SEAL).pending).toEqual(['dance', 'handoff'])
  })
})

describe('vagueness: asking for a choice in prose', () => {
  it('flags the shapes #95 and #96 used', () => {
    expect(vagueness('## Choose\n- [ ] A, B or C (or a mix)')).not.toBeNull()
    expect(vagueness('## Open questions\n- [ ] Button style A, B or C?')).not.toBeNull()
    expect(vagueness('Which option do you prefer, the glide or the dive?')).not.toBeNull()
    expect(vagueness('Notes\n- [ ] Is the Stop circle at the top middle OK?')).not.toBeNull()
  })

  it('does not flag ordinary PR bodies: acceptance criteria, tests, plain checklists', () => {
    const normal = `## What changed
Stop always returns to Start.

## Acceptance criteria
- [x] Regression test passes
- [ ] Verified on the owner's iPhone

## Tests
316 tests, 0 failures.`
    expect(vagueness(normal)).toBeNull()
    expect(vagueness('Fixes the Option A code path; see option handling.')).toBeNull()
    // A heading that reports choices the author already made is not an ask (#96 had "## Choices made (all changeable)").
    expect(vagueness('## Choices made (all changeable)\n- Stop sits at the top middle.')).toBeNull()
    expect(vagueness('## Decisions recorded\nWe went with B.')).toBeNull()
  })

  it('names the actual ask when a body has both a report and a question', () => {
    const v = vagueness('## Choices made (all changeable)\n- x\n\n## Open questions\n- [ ] Style A or B?')
    expect(v.reasons[0]).toMatch(/Open questions/)
  })

  it('accepts ask headings with a trailing phrase or punctuation', () => {
    expect(vagueness('## Questions for you\n1. Which?')).not.toBeNull()
    expect(vagueness('### Choose:\nsomething')).not.toBeNull()
    expect(vagueness('')).toBeNull()
  })

  it('is never vague when a decisions section exists', () => {
    expect(vagueness(SEAL + '\n## Open questions\n- [ ] anything?')).toBeNull()
  })
})

describe('applyAnswers writes the answers into the description', () => {
  const answers = {
    dance: { choices: ['B: Balance a bubble'], note: 'love the bubble' },
    mix: { choices: ["A's clap", "C's slide"] },
    handoff: { choices: ['Dive'] },
    character: { text: 'Make the eyes\na bit bigger' }
  }

  it('ticks exactly the chosen boxes and adds Answer/Note lines, leaving the rest of the body alone', () => {
    const out = applyAnswers(SEAL, answers)
    const d = parseDecisions(out)
    const by = Object.fromEntries(d.questions.map((q) => [q.id, q]))
    expect(by.dance.options.filter((o) => o.checked).map((o) => o.label)).toEqual(['B: Balance a bubble'])
    expect(by.dance.note).toBe('love the bubble')
    expect(by.mix.options.filter((o) => o.checked).map((o) => o.label)).toEqual(["A's clap", "C's slide"])
    expect(by.handoff.options.filter((o) => o.checked).map((o) => o.label)).toEqual(['Dive'])
    expect(by.character.answer).toBe('Make the eyes a bit bigger')
    expect(pendingDecisions(d)).toEqual([])
    expect(out.startsWith('Intro text with images.')).toBe(true)
    expect(out).toContain('## Original notes\n- [ ] not a decision')
  })

  it('is idempotent and replaces earlier answers on change', () => {
    const once = applyAnswers(SEAL, answers)
    expect(applyAnswers(once, answers)).toBe(once)
    const changed = applyAnswers(once, { dance: { choices: ['A: Clap & wiggle'] }, character: { text: 'none' } })
    const by = Object.fromEntries(parseDecisions(changed).questions.map((q) => [q.id, q]))
    expect(by.dance.options.filter((o) => o.checked).map((o) => o.label)).toEqual(['A: Clap & wiggle'])
    expect(by.dance.note).toBeNull()
    expect(by.character.answer).toBe('none')
    expect(changed.match(/\*\*Answer:\*\*/g)).toHaveLength(1)
  })

  it('leaves questions that were not answered untouched', () => {
    const out = applyAnswers(SEAL, { handoff: { choices: ['Glide'] } })
    const by = Object.fromEntries(parseDecisions(out).questions.map((q) => [q.id, q]))
    expect(by.dance.options.every((o) => !o.checked)).toBe(true)
  })

  it('refuses a body with no decisions section', () => {
    expect(() => applyAnswers('plain', {})).toThrow(/no decisions section/)
  })

  it('works when there is no blank line between questions or before the end', () => {
    const tight = '<!-- marvin:decisions -->\n### a: A?\n- [ ] x\n- [ ] y\n### b: B?\n- [ ] p\n- [ ] q'
    const out = applyAnswers(tight, { a: { choices: ['y'], note: 'n1' }, b: { choices: ['p'], note: 'n2' } })
    const by = Object.fromEntries(parseDecisions(out).questions.map((q) => [q.id, q]))
    expect(by.a.note).toBe('n1')
    expect(by.b.note).toBe('n2')
    expect(by.b.options[0].checked).toBe(true)
  })
})

describe('decisionsComment', () => {
  it('summarizes readably and embeds the answers as machine-readable JSON', () => {
    const parsed = parseDecisions(SEAL)
    const c = decisionsComment(parsed, { dance: { choices: ['C: Belly slide & wave'], note: 'cute' }, character: { text: 'none' } })
    expect(c).toContain('### Decisions from the owner')
    expect(c).toContain('**Which launch animation?** C: Belly slide & wave. _Note:_ cute')
    const json = c.match(/```marvin-decisions\n([\s\S]+?)\n```/)[1]
    expect(JSON.parse(json).answers.character.text).toBe('none')
  })
})

describe('assertDecisions (merge server)', () => {
  const PR = 'https://github.com/G-Eskayo/clarity-captions/pull/99'
  const viewing = (body) => vi.fn().mockResolvedValue({ stdout: JSON.stringify({ body }) })

  it('refuses while required decisions are open, naming them', async () => {
    await expect(assertDecisions(PR, viewing(SEAL))).rejects.toMatchObject({
      payload: { code: 'DECISIONS_PENDING', message: expect.stringContaining('dance, handoff') }
    })
  })

  it('passes once they are answered, and passes PRs with no decisions and no asks', async () => {
    const answered = applyAnswers(SEAL, { dance: { choices: ['A: Clap & wiggle'] }, handoff: { choices: ['Glide'] } })
    await expect(assertDecisions(PR, viewing(answered))).resolves.toBeUndefined()
    await expect(assertDecisions(PR, viewing('## Tests\n- [x] passes'))).resolves.toBeUndefined()
  })

  it('refuses a PR that asks in prose with nowhere to answer', async () => {
    await expect(assertDecisions(PR, viewing('## Choose\n- [ ] A, B or C'))).rejects.toMatchObject({ payload: { code: 'DECISIONS_UNSTRUCTURED' } })
  })

  it('fails closed when GitHub cannot be asked', async () => {
    await expect(assertDecisions(PR, vi.fn().mockRejectedValue(new Error('boom')))).rejects.toMatchObject({ payload: { code: 'DECISIONS_UNCHECKED' } })
    await expect(assertDecisions(PR, vi.fn().mockResolvedValue({ stdout: 'not json' }))).rejects.toMatchObject({ payload: { code: 'DECISIONS_UNCHECKED' } })
  })
})

describe('mergePr and the review card', () => {
  it('mergePr refuses open decisions before any gate work or merge', async () => {
    const exec = vi.fn(async () => ({ stdout: JSON.stringify({ body: SEAL, baseRefName: 'main', isDraft: false, files: [] }), stderr: '' }))
    const shouldGate = vi.fn()
    await expect(mergePr('https://github.com/G-Eskayo/marvin/pull/99', exec, () => Promise.resolve(), () => {}, shouldGate))
      .rejects.toMatchObject({ payload: { code: 'DECISIONS_PENDING' } })
    expect(shouldGate).not.toHaveBeenCalled()
    expect(exec.mock.calls.some((c) => c[1]?.[1] === 'merge')).toBe(false)
  })

  it('card: open decisions disable Approve and say so', () => {
    const s = describePrState({ decisions: { present: true, questions: [], problems: [], pending: ['dance', 'handoff'] } })
    expect(s.kind).toBe('decisions-pending')
    expect(s.headline).toBe('Answer the decisions first')
    expect(s.approve).toBe('disabled')
    expect(s.detail).toMatch(/2 decisions/)
  })

  it('card: prose asks are "Too vague: needs options", with a one-click send back and no Approve', () => {
    const s = describePrState({ vague: { reasons: ['"## Choose" asks for a choice'] } })
    expect(s.kind).toBe('needs-options')
    expect(s.headline).toBe('Too vague: needs options')
    expect(s.approve).toBe('hidden')
    expect(s.actions.map((a) => a.id)).toContain('sendBackForOptions')
  })

  it('card: a malformed decisions section blocks Approve too', () => {
    const s = describePrState({ decisions: { present: true, questions: [], problems: ['"x" offers 1 option(s)'], pending: [] } })
    expect(s.kind).toBe('needs-options')
    expect(s.actions.map((a) => a.id)).toContain('sendBackForOptions')
  })

  it('card: answered decisions let a ready PR be approved', () => {
    const s = describePrState({ decisions: { present: true, questions: [], problems: [], pending: [] }, checks: { state: 'passing', failing: [], pending: [] } })
    expect(s.kind).toBe('ready')
    expect(s.approve).toBe('enabled')
  })

  it('a stale DECISIONS_ refusal is not shown as an error once the state explains it', () => {
    const s = describePrState({ decisions: { present: true, questions: [], problems: [], pending: [] } }, { status: 'error', errorMessage: 'DECISIONS_PENDING at request: x' })
    expect(s.kind).not.toBe('error')
  })
})

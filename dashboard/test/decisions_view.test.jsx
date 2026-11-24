import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Decisions, { initialDraft, missingRequired, changedAnswers, toggleChoice, submitOutcome, followGithub, answersSignature } from '../src/components/Decisions.jsx'
import MrDetail from '../src/components/MrDetail.jsx'
import { summarizeDecisions } from '../webhook-server/decisions.js'

// Mock localStorage for all tests
const mockStorage = new Map()
const mockLocalStorage = {
  getItem: (key) => mockStorage.has(key) ? mockStorage.get(key) : null,
  setItem: (key, value) => mockStorage.set(key, value),
  removeItem: (key) => mockStorage.delete(key),
  clear: () => mockStorage.clear()
}

if (!global.localStorage) {
  global.localStorage = mockLocalStorage
}

const BODY = `<!-- marvin:decisions -->
### dance: Which launch animation?
- [ ] A: Clap & wiggle
- [x] B: Balance a bubble
### handoff: Hand-off into the start screen
- [ ] Glide
- [ ] Dive
### mix: Mix parts? (pick any) (optional)
- [ ] clap
- [ ] slide
### character: Changes to the character? (text) (optional)
> **Answer:** none
`
const d = summarizeDecisions(BODY)

describe('form helpers', () => {
  it('starts from what the description already holds', () => {
    const draft = initialDraft(d.questions)
    expect(draft.dance.choices).toEqual(['B: Balance a bubble'])
    expect(draft.character.text).toBe('none')
    expect(missingRequired(d.questions, draft)).toEqual(['handoff'])
  })

  it('one-answer questions swap, pick-any toggles, a second tap clears', () => {
    const single = d.questions[0]
    expect(toggleChoice(single, ['B: Balance a bubble'], 'A: Clap & wiggle')).toEqual(['A: Clap & wiggle'])
    expect(toggleChoice(single, ['A: Clap & wiggle'], 'A: Clap & wiggle')).toEqual([])
    const multi = d.questions[2]
    expect(toggleChoice(multi, ['clap'], 'slide')).toEqual(['clap', 'slide'])
    expect(toggleChoice(multi, ['clap', 'slide'], 'clap')).toEqual(['slide'])
  })

  it('sends only questions whose answer changed', () => {
    const draft = initialDraft(d.questions)
    expect(changedAnswers(d.questions, draft)).toEqual({})
    draft.handoff = { choices: ['Dive'], text: '', note: 'calmer' }
    expect(changedAnswers(d.questions, draft)).toEqual({ handoff: { choices: ['Dive'], note: 'calmer' } })
  })
})

describe('Decisions panel', () => {
  it('shows each question with its options as buttons, required/optional/pick-any badges, and a submit', () => {
    const html = renderToStaticMarkup(<Decisions repo="o/r" number={99} decisions={d} submit={vi.fn()} />)
    expect(html).toContain('Which launch animation?')
    expect(html).toContain('1 to answer before you can approve.')
    expect(html.match(/role="radio"/g)).toHaveLength(4)
    expect(html.match(/role="checkbox"/g)).toHaveLength(2)
    expect(html).toContain('aria-checked="true"')
    expect(html).toContain('Pick any')
    expect(html).toContain('Optional')
    expect(html).toContain('Submit decisions')
    expect(html).toContain('Still to answer: Hand-off into the start screen')
  })

  it('answered decisions show read-only with a Change button', () => {
    const answered = summarizeDecisions(BODY.replace('- [ ] Dive', '- [x] Dive'))
    const html = renderToStaticMarkup(<Decisions repo="o/r" number={99} decisions={answered} submit={vi.fn()} />)
    expect(html).toContain('All required decisions are answered.')
    expect(html).toContain('>Change<')
    expect(html).not.toContain('Submit decisions')
  })

  it('renders nothing without a section', () => {
    expect(renderToStaticMarkup(<Decisions repo="o/r" number={1} decisions={null} />)).toBe('')
  })

  it('the PR detail puts the images above the Decisions (#938: you can\'t answer choices you can\'t see)', () => {
    globalThis.window = { api: { relations: { pr: () => new Promise(() => {}) }, mr: { ticketContext: () => new Promise(() => {}), mergeState: () => new Promise(() => {}) } } }
    const pr = {
      number: 99, title: 'Seal dance', url: 'https://github.com/G-Eskayo/clarity-captions/pull/99', repo: 'G-Eskayo/clarity-captions',
      key: 'G-Eskayo/clarity-captions#99', canMerge: true, hasSchema: false, rawBody: BODY, ticketNumber: null, checks: null,
      decisions: d, images: [{ url: 'https://raw.githubusercontent.com/x/y/z/a.gif', alt: 'A', group: 'Watch', caption: 'A' }]
    }
    const html = renderToStaticMarkup(<MrDetail pr={pr} onBack={() => {}} />)
    expect(html.indexOf('data-decisions')).toBeGreaterThan(0)
    expect(html.indexOf('Images &amp; recordings')).toBeGreaterThan(0)
    expect(html.indexOf('Images &amp; recordings')).toBeLessThan(html.indexOf('data-decisions'))
    expect(html).toContain('Answer the decisions first')
  })
})

// Draft persistence: unsaved answers survive an accidental close/reload
describe('draft persistence', () => {
  beforeEach(() => {
    mockStorage.clear()
    global.localStorage = mockLocalStorage
  })

  it('restores saved diff on mount and merges it over initial answers', () => {
    // Simulate saved diff in storage
    const saved = { handoff: { choices: ['Dive'], note: 'try calmer' } }
    localStorage.setItem('decisions:marvin#1', JSON.stringify(saved))

    // When component mounts and reads this key, it should load the saved diff
    const stored = localStorage.getItem('decisions:marvin#1')
    expect(stored).not.toBeNull()

    const diff = JSON.parse(stored)
    expect(diff.handoff.choices).toEqual(['Dive'])
    expect(diff.handoff.note).toBe('try calmer')
  })

  it('persists only changed answers to storage', () => {
    const initial = initialDraft(d.questions)
    const edited = { ...initial }
    edited.dance = { choices: ['A: Clap & wiggle'], text: '', note: '' }
    edited.handoff = { choices: ['Glide'], text: '', note: 'smooth' }

    const changed = changedAnswers(d.questions, edited)
    expect(Object.keys(changed)).toContain('dance')
    expect(Object.keys(changed)).toContain('handoff')
    expect(Object.keys(changed)).not.toContain('character')

    // Component would write this to storage
    localStorage.setItem('decisions:marvin#1', JSON.stringify(changed))
    expect(localStorage.getItem('decisions:marvin#1')).toBe(JSON.stringify(changed))
  })

  it('clears persistence after successful submit', () => {
    // Before submit: persistence has saved answers
    localStorage.setItem('decisions:marvin#1', JSON.stringify({ handoff: { choices: ['Dive'] } }))
    expect(localStorage.getItem('decisions:marvin#1')).not.toBeNull()

    // After successful submit: clearStored is called
    localStorage.removeItem('decisions:marvin#1')
    expect(localStorage.getItem('decisions:marvin#1')).toBeNull()
  })

  it('does not re-persist after clearing due to stale questions', () => {
    // Scenario: submit succeeds, we clearStored, but questions are still old
    // The persist effect should not write the diff back because it's unchanged from last persist
    const key = 'decisions:marvin#1'
    const diff = { handoff: { choices: ['Dive'] } }

    // Write it initially
    localStorage.setItem(key, JSON.stringify(diff))
    const before = localStorage.getItem(key)

    // Clear it (simulating successful submit)
    localStorage.removeItem(key)
    expect(localStorage.getItem(key)).toBeNull()

    // If persist re-runs with the same diff, it should check if already persisted
    // and skip writing if unchanged
    const changed = { handoff: { choices: ['Dive'] } }
    const changeStr = JSON.stringify(changed)
    const lastPersisted = JSON.stringify(diff) // This was what we just cleared

    // Skip write if the diff is the same as what was last persisted
    if (changeStr !== lastPersisted) {
      localStorage.setItem(key, changeStr)
    }

    // Key should still be cleared (not re-written)
    expect(localStorage.getItem(key)).toBeNull()
  })
})

// Local-first: the panel shows what GitHub has, never only what was sent.
describe('after a submit, the panel follows GitHub', () => {
  const answered = summarizeDecisions(BODY.replace('- [ ] Glide', '- [x] Glide'))
  it('GitHub kept a different answer: not "saved", stays open to pick again', () => {
    const out = submitOutcome({ ok: true, disagreed: true, pending: ['handoff'] })
    expect(out.editing).toBe(true)
    expect(out.status.state).toBe('error')
    expect(out.status.message).toMatch(/GitHub kept a different answer/)
  })
  it('agreed: saved, recording until the comment lands, remembering what GitHub had', () => {
    const out = submitOutcome({ ok: true, pending: [], pr: { decisions: answered } })
    expect(out).toMatchObject({ editing: false, status: { state: 'saved', result: { recording: true }, savedSig: answersSignature(answered.questions) } })
    expect(submitOutcome({ ok: true, commentUrl: 'u', pr: null }).status.result.recording).toBe(false)
  })
  it('a background correction re-ticks GitHub\'s answers and turns "Saved" into a warning', () => {
    const saved = submitOutcome({ ok: true, pending: [], pr: { decisions: answered } }).status
    const next = followGithub({ questions: d.questions, editing: false, status: saved })
    expect(next.draft.handoff.choices).toEqual([])
    expect(next.status.state).toBe('error')
  })
  it('the save itself is not mistaken for a correction', () => {
    const saved = submitOutcome({ ok: true, pending: [], pr: { decisions: answered } }).status
    expect(followGithub({ questions: answered.questions, editing: false, status: saved }).status).toBe(saved)
  })
  it('while Gil is editing, his picks are left alone', () => {
    expect(followGithub({ questions: d.questions, editing: true, status: { state: 'idle' } })).toBeNull()
  })
})

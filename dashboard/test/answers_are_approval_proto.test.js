import { describe, it, expect } from 'vitest'
// MR Review: answers are the approval (marvin#924), the mock-up's logic. These try to break answerState(), the one rule
// that names the Decisions card's button. It is a classic script (it opens from Finder), so it sets globalThis.AnswerState.
import '../../docs/design/answers-are-approval-924/answer_state.js'

const { answerState, canPress } = globalThis.AnswerState

const opt = (label, built = false) => ({ label, built })
const handoff = { id: 'handoff', question: 'Hand-off into the start screen', kind: 'pick-one', required: true, options: [opt('Glide', true), opt('Dive')] }
const extras = { id: 'extras', question: 'Which extras?', kind: 'pick-any', required: true, options: [opt('Sound', true), opt('Haptic', true), opt('Confetti')] }
const tone = { id: 'tone', question: 'Card colour', kind: 'pick-one', required: false, options: [opt('Blue', true), opt('Grey')] }
const words = { id: 'words', question: 'Anything to change in the wording?', kind: 'text', required: false, options: [] }
const code = [handoff, extras, tone, words]
const unbuilt = (qs) => qs.map((q) => ({ ...q, options: q.options.map((o) => ({ ...o, built: false })) }))

describe('every answer matches what is built: one press merges', () => {
  it('untouched, the built options are the answers, and the button merges', () => {
    const s = answerState({ decisions: code })
    expect(s.action).toBe('merge')
    expect(s.label).toBe('Merge with these answers')
    expect(s.picks).toEqual({ handoff: ['Glide'], extras: ['Sound', 'Haptic'], tone: ['Blue'], words: '' })
  })

  it('the pre-selected answers are marked not yet sent; picking the same thing again makes it yours', () => {
    expect(answerState({ decisions: code }).unsent).toEqual(['handoff', 'extras', 'tone'])
    const s = answerState({ decisions: code, picks: { handoff: ['Glide'] } })
    expect(s.unsent).toEqual(['extras', 'tone'])
    expect(s.action).toBe('merge')
  })

  it('pick-any in a different order is still the same answer', () => {
    expect(answerState({ decisions: code, picks: { extras: ['Haptic', 'Sound'] } }).action).toBe('merge')
  })

  it('an optional question cleared to nothing is no answer, so it changes nothing', () => {
    expect(answerState({ decisions: code, picks: { tone: [] } }).action).toBe('merge')
  })

  it('an optional text question left empty does not stop the merge', () => {
    expect(answerState({ decisions: code, picks: { words: '' } }).action).toBe('merge')
  })
})

describe('anything different never merges', () => {
  it('one changed pick-one answer sends it back, and the reason names both answers', () => {
    const s = answerState({ decisions: code, picks: { handoff: ['Dive'] } })
    expect(s.action).toBe('send-back')
    expect(s.label).toBe('Send back with answers')
    expect(s.reason).toContain('Dive')
    expect(s.reason).toContain('Glide')
  })

  it('pick-any with one built option dropped differs', () => {
    expect(answerState({ decisions: code, picks: { extras: ['Sound'] } }).action).toBe('send-back')
  })

  it('pick-any with an extra option added differs', () => {
    expect(answerState({ decisions: code, picks: { extras: ['Sound', 'Haptic', 'Confetti'] } }).action).toBe('send-back')
  })

  it('an optional question answered differently from what is built differs', () => {
    expect(answerState({ decisions: code, picks: { tone: ['Grey'] } }).action).toBe('send-back')
  })

  it('a typed note sends it back even when every answer matches, and says which question', () => {
    const s = answerState({ decisions: code, notes: { tone: 'a touch darker' } })
    expect(s.action).toBe('send-back')
    expect(s.reason).toContain('Card colour')
  })

  it('a whitespace-only note is not a note', () => {
    expect(answerState({ decisions: code, notes: { tone: '  \n\t ' } }).action).toBe('merge')
  })

  it('a written answer to a text question goes back to MARVIN', () => {
    expect(answerState({ decisions: code, picks: { words: 'Say "ready", not "done"' } }).action).toBe('send-back')
    expect(answerState({ decisions: code, picks: { words: '   ' } }).action).toBe('merge')
  })

  it('answering a question nothing was built for sends it back (it can not match what is built)', () => {
    const later = { id: 'later', question: 'Do the iPad too?', kind: 'pick-one', required: false, options: [opt('Yes'), opt('Not now')] }
    expect(answerState({ decisions: [...code, later] }).action).toBe('merge')
    expect(answerState({ decisions: [...code, later], picks: { later: ['Not now'] } }).action).toBe('send-back')
  })

  it('a label that is not on the list is ignored, not taken as an answer', () => {
    const s = answerState({ decisions: code, picks: { handoff: ['Teleport'] } })
    expect(s.action).toBe('disabled')
  })
})

describe('a required decision unanswered: the button is disabled', () => {
  it('required with no built default and nothing picked: Answer 1 more', () => {
    const q = { ...handoff, options: [opt('Glide'), opt('Dive')] }
    const s = answerState({ decisions: [q, extras] })
    expect(s.action).toBe('disabled')
    expect(s.label).toBe('Answer 1 more')
    expect(s.missing).toEqual(['handoff'])
    expect(canPress(s)).toBe(false)
  })

  it('a required built answer cleared by hand is unanswered again', () => {
    const s = answerState({ decisions: code, picks: { handoff: [], extras: [] } })
    expect(s.label).toBe('Answer 2 more')
  })

  it('pick-one with two picked is not an answer', () => {
    expect(answerState({ decisions: code, picks: { handoff: ['Glide', 'Dive'] } }).action).toBe('disabled')
  })

  it('a required text question needs real text, not spaces', () => {
    const must = { ...words, required: true }
    expect(answerState({ decisions: [handoff, must], picks: { words: '  ' } }).label).toBe('Answer 1 more')
  })

  it('unanswered wins over a note: you answer before anything is sent', () => {
    const q = { ...handoff, options: [opt('Glide'), opt('Dive')] }
    expect(answerState({ decisions: [q, extras], notes: { extras: 'hm' } }).action).toBe('disabled')
  })

  it('all required answered, one with a choice that is not built: Send back, never disabled', () => {
    const q = { ...handoff, options: [opt('Glide'), opt('Dive')] }
    expect(answerState({ decisions: [q, extras], picks: { handoff: ['Dive'] } }).action).toBe('send-back')
  })
})

describe('a mock-up or plan PR is a ballot', () => {
  const ballot = unbuilt([handoff, tone])

  it('nothing is pre-selected and the required one must be picked', () => {
    const s = answerState({ decisions: ballot, plan: true })
    expect(s.action).toBe('disabled')
    expect(s.unsent).toEqual([])
  })

  it('answered, the button sends and never merges, even with a note', () => {
    const s = answerState({ decisions: ballot, plan: true, picks: { handoff: ['Dive'] }, notes: { tone: 'either is fine' } })
    expect(s.action).toBe('send')
    expect(s.label).toBe('Send answers')
  })

  it('a plan with a stray built marker still pre-selects nothing', () => {
    const s = answerState({ decisions: [handoff], plan: true })
    expect(s.action).toBe('disabled')
  })
})

describe('old-format PRs fall back to the two steps', () => {
  it('no built markers anywhere: Submit decisions, then Approve & merge', () => {
    const s = answerState({ decisions: unbuilt(code), picks: { handoff: ['Glide'], extras: ['Sound'] } })
    expect(s.action).toBe('two-step')
    expect(s.label).toBe('Submit decisions')
  })

  it('a pick-one question with two built answers is broken, so it stays two steps', () => {
    const twice = { ...handoff, options: [opt('Glide', true), opt('Dive', true)] }
    expect(answerState({ decisions: [twice] }).action).toBe('two-step')
  })

  it('no decisions at all is plain Approve & merge', () => {
    expect(answerState({ decisions: [] }).action).toBe('two-step')
    expect(answerState().label).toBe('Approve & merge')
    expect(answerState({ decisions: null }).action).toBe('two-step')
  })
})

describe('pressing twice, and a merge that fails', () => {
  it('while sending, the button is busy and a second press is refused', () => {
    const s = answerState({ decisions: code, status: 'sending' })
    expect(s.busy).toBe(true)
    expect(s.label).toBe('Merging…')
    expect(canPress(s)).toBe(false)
    expect(answerState({ decisions: code, notes: { tone: 'x' }, status: 'sending' }).label).toBe('Sending…')
  })

  it('the answers saved but the merge failed: they stay, the failure shows, and it offers the merge again', () => {
    const s = answerState({ decisions: code, status: 'merge-failed', failure: 'GitHub checks failed' })
    expect(s.action).toBe('merge')
    expect(s.label).toBe('Try the merge again')
    expect(s.reason).toContain('saved')
    expect(s.reason).toContain('GitHub checks failed')
    expect(s.unsent).toEqual([])
    expect(canPress(s)).toBe(true)
  })

  it('a changed answer after a failed merge is a send back, not a retry', () => {
    expect(answerState({ decisions: code, picks: { handoff: ['Dive'] }, status: 'merge-failed' }).action).toBe('send-back')
  })

  it('the inputs are never changed', () => {
    const picks = { extras: ['Haptic', 'Sound', 'Sound'] }
    const frozen = JSON.stringify({ code, picks })
    answerState({ decisions: code, picks })
    expect(JSON.stringify({ code, picks })).toBe(frozen)
  })
})

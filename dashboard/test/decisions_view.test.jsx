import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Decisions, { initialDraft, missingRequired, changedAnswers, toggleChoice } from '../src/components/Decisions.jsx'
import MrDetail from '../src/components/MrDetail.jsx'
import { summarizeDecisions } from '../webhook-server/decisions.js'

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

  it('the PR detail puts Decisions above the images', () => {
    globalThis.window = { api: { relations: { pr: () => new Promise(() => {}) }, mr: { ticketContext: () => new Promise(() => {}), mergeState: () => new Promise(() => {}) } } }
    const pr = {
      number: 99, title: 'Seal dance', url: 'https://github.com/G-Eskayo/clarity-captions/pull/99', repo: 'G-Eskayo/clarity-captions',
      key: 'G-Eskayo/clarity-captions#99', canMerge: true, hasSchema: false, rawBody: BODY, ticketNumber: null, checks: null,
      decisions: d, images: [{ url: 'https://raw.githubusercontent.com/x/y/z/a.gif', alt: 'A', group: 'Watch', caption: 'A' }]
    }
    const html = renderToStaticMarkup(<MrDetail pr={pr} onBack={() => {}} />)
    expect(html.indexOf('data-decisions')).toBeGreaterThan(0)
    expect(html.indexOf('data-decisions')).toBeLessThan(html.indexOf('Images &amp; recordings'))
    expect(html).toContain('Answer the decisions first')
  })
})

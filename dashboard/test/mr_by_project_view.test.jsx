import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { GroupingToggle, ProjectGroup, HelperChip } from '../src/components/MrGroups.jsx'
import { groupPrs } from '../src/lib/mr_groups.js'

// MR Review by project, wired into the real tab (marvin#848), with the owner's answers on #767.
const PROJECTS = [
  { id: 'marvin', name: 'MARVIN', repo: 'G-Eskayo/marvin', status: 'active' },
  { id: 'clarity-captions', name: 'Seal Speak', repo: 'G-Eskayo/clarity-captions', status: 'active' },
  { id: 'nourished', name: 'nourished', repo: 'G-Eskayo/nourished', status: 'active' }
]
const pr = (number, extra = {}) => ({
  number, repo: 'G-Eskayo/marvin', key: `${extra.repo || 'G-Eskayo/marvin'}#${number}`, title: `PR ${number}`,
  url: `https://github.com/${extra.repo || 'G-Eskayo/marvin'}/pull/${number}`,
  checks: { state: 'passing', failing: [], pending: [] }, labels: [], isDraft: false, ...extra
})
const text = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
const card = (p) => <div data-card={p.number}>card {p.number}</div>
const groups = groupPrs([pr(1), pr(2, { isDraft: true }), pr(9, { repo: 'G-Eskayo/clarity-captions', isDraft: true })], PROJECTS, { empty: 'show', isLive: (p) => p.status === 'active' })
const byId = Object.fromEntries(groups.map((g) => [g.id, g]))
const render = (g, extra = {}) => renderToStaticMarkup(<ProjectGroup group={g} collapsed={false} onToggle={() => {}} renderPr={card} {...extra} />)

describe('GroupingToggle: By project | All', () => {
  it('two buttons, the current one pressed', () => {
    const h = renderToStaticMarkup(<GroupingToggle grouping="project" setGrouping={() => {}} />)
    expect(text(h)).toBe('By project All')
    expect(h).toMatch(/aria-pressed="true"[^>]*>By project/)
    expect(h).toMatch(/aria-pressed="false"[^>]*>All/)
  })
})

describe('ProjectGroup', () => {
  it('header: name, count, how many need you, the summary', () => {
    const t = text(render(byId.marvin))
    expect(t).toMatch(/^▾ MARVIN 2 1 needs you 1 to approve/)
  })
  it('open: each tier has its heading, cards in order', () => {
    const h = render(byId.marvin)
    expect(text(h)).toMatch(/Needs you card 1 Draft card 2/)
  })
  it('collapsed: the header only, no cards', () => {
    const h = render(byId.marvin, { collapsed: true })
    expect(h).not.toContain('data-card')
    expect(text(h)).toMatch(/^▸ MARVIN/)
    expect(h).toContain('aria-expanded="false"')
  })
  it('the name and the arrow are one button: tapping the name collapses or expands, the same as the arrow', () => {
    const h = render(byId.marvin)
    const buttons = h.match(/<button[\s\S]*?<\/button>/g)
    expect(buttons).toHaveLength(1)
    expect(text(buttons[0])).toMatch(/▾ MARVIN/)
    expect(buttons[0]).toContain('aria-expanded="true"')
  })
  it('a group with nothing for you says so', () => {
    expect(text(render(byId['clarity-captions'], { collapsed: true }))).toMatch(/Seal Speak 1 nothing for you · 1 draft/)
  })
  it('an empty project is shown dimmed with "no open MRs", and has no needs-you pill', () => {
    const h = render(byId.nourished, { collapsed: true })
    expect(h).toContain('data-empty="1"')
    expect(text(h)).toBe('▸ nourished 0 no open MRs')
  })
  it('Other says why each card is there', () => {
    const [other] = groupPrs([pr(4, { repo: 'someone/else' })], PROJECTS)
    expect(text(render(other))).toContain('Other')
    expect(text(render(other))).toMatch(/its repo isn.t in the project catalog/)
  })
})

describe('HelperChip', () => {
  it('running, finished and failed, as helper-tab titles them', () => {
    expect(text(renderToStaticMarkup(<HelperChip helper={{ state: 'running', label: '● MARVIN · #848 x' }} />))).toBe('● MARVIN · #848 x')
    expect(renderToStaticMarkup(<HelperChip helper={{ state: 'failed', label: '✗ MARVIN · #848 x' }} />)).toContain('data-helper="failed"')
  })
  it('no helper, no chip', () => {
    expect(renderToStaticMarkup(<HelperChip helper={null} />)).toBe('')
  })
})

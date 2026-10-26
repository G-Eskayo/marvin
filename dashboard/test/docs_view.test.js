// #570: the Docs tab's drill-down rules (src/lib/docs_view.js). One chip row chooses the kind, while browsing and searching.
import { describe, it, expect } from 'vitest'
import { groupTree, visibleKinds, toggleChip, mainView, searchGroups, hiddenNote, countLine, overviewPicks, formatDay, matchedBy, deliverableSummary, resultKind, rankedResults } from '../src/lib/docs_view.js'

const tree = [
  { path: 'PROJECT.md', label: 'Project card' },
  { path: 'CONTEXT.md', label: 'CONTEXT.md' },
  { path: 'README.md', label: 'README.md' },
  { section: 'docs/adr/', items: [{ path: 'docs/adr/0001-a.md' }, { path: 'docs/adr/0002-b.md' }, { path: 'docs/adr/0003-c.md' }, { path: 'docs/adr/0004-d.md' }] },
  { section: 'docs/', items: [{ path: 'docs/a.md' }, { path: 'docs/b.md' }] },
  { section: 'notebooks', items: [{ path: 'x.ipynb' }] }
]
const deliv = [{ path: 'seal-1', isDir: true, count: 5 }, { path: 'x.diff', isDir: false, kinds: ['Code'] }]

describe('groupTree', () => {
  it('Decisions are docs/adr/; Docs are everything else, the card included; Deliverables are the matched items', () => {
    const g = groupTree(tree, deliv)
    expect(g.decisions.count).toBe(4)
    expect(g.docs.count).toBe(6)
    expect(g.docs.sections.map((s) => s.section)).toEqual(['docs/', 'notebooks'])
    expect(g.deliverables.count).toBe(2)
  })
  it('copes with nothing', () => {
    expect(groupTree(null, null)).toMatchObject({ docs: { count: 0 }, decisions: { count: 0 }, deliverables: { count: 0 } })
  })
})

describe('the chip row', () => {
  it('no chip = every group; chips = only those', () => {
    expect(visibleKinds(new Set())).toEqual(['docs', 'decisions', 'deliverables'])
    expect(visibleKinds(new Set(['decisions', 'docs']))).toEqual(['docs', 'decisions'])
  })
  it('toggles without mutating', () => {
    const a = new Set(['docs'])
    const b = toggleChip(a, 'docs')
    expect(a.has('docs')).toBe(true)
    expect(b.size).toBe(0)
    expect(toggleChip(b, 'deliverables').has('deliverables')).toBe(true)
  })
})

describe('mainView: one control per level', () => {
  const only = new Set(['deliverables'])
  it('the grid shows when only Deliverables is active and nothing below the project is selected', () => {
    expect(mainView({ chips: only, selection: { type: 'doc', path: 'PROJECT.md' } })).toBe('grid')
    expect(mainView({ chips: only, selection: null })).toBe('grid')
    expect(mainView({ chips: new Set(['deliverables', 'docs']), selection: null })).toBe('overview')
  })
  it('a selected folder shows its grid, a file opens, the card is the overview, a search wins', () => {
    expect(mainView({ chips: new Set(), selection: { type: 'folder', path: 'x' } })).toBe('folder')
    expect(mainView({ chips: only, selection: { type: 'deliverable', path: 'x/a.png' } })).toBe('file')
    expect(mainView({ chips: new Set(), selection: { type: 'doc', path: 'CONTEXT.md' } })).toBe('doc')
    expect(mainView({ chips: new Set(), selection: { type: 'doc', path: 'PROJECT.md' } })).toBe('overview')
    expect(mainView({ chips: only, selection: { type: 'folder' }, searching: true })).toBe('search')
  })
})

describe('search with chips (mock-up f-4)', () => {
  const results = [
    { repo: 'c', path: 'CONTEXT.md' }, { repo: 'c', path: 'docs/x.md' }, { repo: 'c', path: 'docs/adr/0001.md' },
    { repo: 'c', path: 'outbox/a/', kind: 'deliverable', isDir: true }, { repo: 'c', path: 'outbox/a/b.md', kind: 'deliverable' }, { repo: 'c', path: 'outbox/a/c.png', kind: 'deliverable' }
  ]
  it('groups by kind and counts what the chips hide', () => {
    const g = searchGroups(results, new Set(['deliverables']))
    expect(g.groups.map((x) => [x.kind, x.results.length])).toEqual([['deliverables', 3]])
    expect(g.hidden).toEqual({ docs: 2, decisions: 1 })
    expect(hiddenNote(g.hidden)).toBe('2 Docs and 1 Decision hidden')
    expect(countLine({ query: 'app store', docCount: 295, deliverableCount: 165, chips: new Set(['deliverables']), grouped: g })).toBe(
      '3 of 6 results for “app store” across 295 docs and 165 deliverables · showing Deliverables (the chip row filters results too) · 2 Docs and 1 Decision hidden'
    )
  })
  it('with no chip, every group shows and nothing is hidden', () => {
    const g = searchGroups(results, new Set())
    expect(g.groups.map((x) => x.kind)).toEqual(['docs', 'decisions', 'deliverables'])
    expect(countLine({ query: 'q', docCount: 1, deliverableCount: 1, chips: new Set(), grouped: g })).toBe('6 results for “q” across 1 doc and 1 deliverable')
  })
  it('three hidden kinds read as a list', () => {
    expect(hiddenNote({ docs: 1, decisions: 2, deliverables: 3 })).toBe('1 Doc, 2 Decisions and 3 Deliverables hidden')
    expect(hiddenNote({})).toBe('')
  })
  it('a result is a decision only under docs/adr/', () => {
    expect(resultKind({ path: 'docs/adr-notes.md' })).toBe('docs')
    expect(resultKind({ path: 'docs/adr/0001.md' })).toBe('decisions')
    expect(resultKind({ path: 'outbox/docs/adr/x.md', kind: 'deliverable' })).toBe('deliverables')
  })
})

describe('overview and labels', () => {
  it('picks the first four docs (not the card) and the latest three decisions', () => {
    const p = overviewPicks(groupTree(tree, deliv))
    expect(p.docs.map((d) => d.path)).toEqual(['CONTEXT.md', 'README.md', 'docs/a.md', 'docs/b.md'])
    expect(p.decisions.map((d) => d.path)).toEqual(['docs/adr/0004-d.md', 'docs/adr/0003-c.md', 'docs/adr/0002-b.md'])
  })
  it('formats days and match reasons, and never throws on junk', () => {
    expect(formatDay('2026-10-21')).toBe('21 Oct 2026')
    expect(formatDay('2026-13-01')).toBe('')
    expect(formatDay(null)).toBe('')
    expect(matchedBy({ reason: "phrase 'seal speak' in its docs" })).toBe("matched by phrase 'seal speak' in its docs")
    expect(matchedBy({})).toMatch(/^not matched/)
    expect(deliverableSummary({ isDir: true, count: 1 })).toBe('Folder · 1 file')
    expect(deliverableSummary({ isDir: false, kinds: ['Code'] })).toBe('Code · from ~/.claude/outbox')
  })
})

// #611 (Gil, 2026-10-22): one list ranked by match, best first whatever its kind, each result tagged with its kind.
describe('rankedResults (#611)', () => {
  const r = (path, score, kind = null) => ({ repo: 'marvin', path, score, kind })
  const results = [
    r('CONTEXT.md', 11),
    r('outbox/marvin-merge-system-2026-10-21/merge-system.html', 32, 'deliverable'),
    r('docs/adr/0026-concurrent-dispatch-smart-merge.md', 5),
    r('outbox/marvin-merge-system-2026-10-21/', 28, 'deliverable')
  ]

  it('puts the best match first even when it is a deliverable', () => {
    const out = rankedResults(results, new Set())
    expect(out.map((x) => x.score)).toEqual([32, 28, 11, 5])
  })

  it('tags each result Doc, Decision or Deliverable', () => {
    const out = rankedResults(results, new Set())
    expect(out.map((x) => x.tag)).toEqual(['Deliverable', 'Deliverable', 'Doc', 'Decision'])
  })

  it('the chip row still filters, keeping the rank order', () => {
    expect(rankedResults(results, new Set(['docs', 'decisions'])).map((x) => x.tag)).toEqual(['Doc', 'Decision'])
  })

  it('keeps the original order on equal scores and tolerates no results', () => {
    const tie = [r('a.md', 3), r('docs/adr/1.md', 3), r('b.md', 3)]
    expect(rankedResults(tie, new Set()).map((x) => x.path)).toEqual(['a.md', 'docs/adr/1.md', 'b.md'])
    expect(rankedResults(undefined, new Set())).toEqual([])
  })

  it('does not mutate the results it is given', () => {
    const copy = JSON.parse(JSON.stringify(results))
    rankedResults(results, new Set())
    expect(results).toEqual(copy)
  })
})

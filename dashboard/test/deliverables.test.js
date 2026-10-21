// #570: outbox items matched to projects (deliverables.js), against a throwaway HOME (never the real ~/.claude).
// Names are the real outbox names the design measured (docs/plans/docs-files-merge.md §2), plus hostile ones.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, symlinkSync, utimesSync, readFileSync } from 'fs'
import { tmpdir, homedir } from 'os'
import path from 'path'
import { createDeliverables, buildContext, matchName, wordsOf, UNSORTED_ID, deliverableDocs } from '../electron/main/deliverables.js'
import { listOutboxDir, summarizeOutbox, outboxPreview, DIR_LIMIT } from '../electron/main/outbox.js'

let home, prevHome, root
beforeEach(() => {
  prevHome = process.env.HOME
  home = mkdtempSync(path.join(tmpdir(), 'deliv-home-'))
  process.env.HOME = home
  root = path.join(home, '.claude', 'outbox')
  mkdirSync(root, { recursive: true })
})
afterEach(() => {
  process.env.HOME = prevHome
  rmSync(home, { recursive: true, force: true })
})
const put = (rel, data = 'x') => {
  mkdirSync(path.dirname(path.join(root, rel)), { recursive: true })
  writeFileSync(path.join(root, rel), data)
}

const projects = [
  { id: 'marvin', name: 'marvin', repo: 'G-Eskayo/marvin', status: 'active', localPaths: ['/Users/x/.agents'] },
  { id: 'clarity-captions', name: 'clarity-captions', repo: 'G-Eskayo/clarity-captions', status: 'active', localPaths: ['/Users/x/Developer/clarity-captions'] },
  { id: 'paper-dive', name: 'paper-dive', repo: 'G-Eskayo/paper-dive', status: 'active', localPaths: [] },
  { id: 'resume-tailor', name: 'resume-tailor', repo: 'G-Eskayo/resume-tailor', status: 'active', localPaths: [] },
  { id: 'mitre-technique-prediction', name: 'mitre-technique-prediction', repo: 'G-Eskayo/mitre-technique-prediction', status: 'active', localPaths: [] },
  { id: 'ml-powered-resume-selector-using-naive-bayes', name: 'ML-Powered-Resume-Selector-using-Naive-Bayes', repo: 'G-Eskayo/ML-Powered-Resume-Selector-using-Naive-Bayes', status: 'dormant', localPaths: [] },
  { id: 'anomaly-detection-v2', name: 'anomaly-detection-v2', repo: 'G-Eskayo/anomaly-detection-v2', status: 'active', localPaths: [] },
  { id: 'ml-unsupervised-learning-anomaly-detection-project', name: 'ML_unsupervised_learning-anomaly-detection-project', repo: 'G-Eskayo/ML_unsupervised_learning-anomaly-detection-project', status: 'active', localPaths: [] },
  { id: 'marvin-mobile', name: 'marvin-mobile', repo: 'G-Eskayo/marvin-mobile', status: 'active', localPaths: [] },
  { id: 'killer-sudoku', name: 'killer-sudoku', repo: 'G-Eskayo/killer-sudoku', status: 'active', localPaths: [] }
]
const docsText = {
  'clarity-captions': 'seal speak is the store name. seal speak ships. seal speak. seal speak beta. seal speak',
  marvin: 'the research colony runs daily. research colony digest. seal speak was mentioned. seal speak too',
  'killer-sudoku': 'settings screen'
}
const context = (over = {}) => ({ projects, overrides: {}, maxNumber: { 'G-Eskayo/marvin': 561, 'G-Eskayo/clarity-captions': 148 }, docsText, home: '/Users/x', ...over })
const ctx = (over) => buildContext(context(over))

describe('wordsOf', () => {
  it('drops dates and the extension', () => {
    expect(wordsOf('seal-speak-ipad-2026-10-21')).toEqual(['seal', 'speak', 'ipad'])
    expect(wordsOf('settings.json.pre-home-202610161406')).toEqual(['settings', 'json'])
    expect(wordsOf('readme-diffs-2026-10-05.diff')).toEqual(['readme', 'diffs'])
  })
  it('survives emoji, 300-character names and empty strings', () => {
    expect(wordsOf('🦭-seal')).toEqual(['seal'])
    expect(wordsOf('a'.repeat(300)).length).toBe(1)
    expect(wordsOf('')).toEqual([])
  })
})

describe('the tiers (real outbox names)', () => {
  const m = (name, top = true) => matchName(ctx(), name, { top })
  it('name: the longest project slug wins, and a number after it is the ticket', () => {
    expect(m('marvin-402-files-viewer-2026-10-21')).toMatchObject({ id: 'marvin', how: 'name', ticket: 402 })
    expect(m('clarity-captions-xcode-string-churn-2026-10-20')).toMatchObject({ id: 'clarity-captions', how: 'name' })
    expect(m('marvin-mobile-notes.md')).toMatchObject({ id: 'marvin-mobile' }) // longer than 'marvin'
  })
  it('inside-name: a run inside one slug; one word only when it starts the slug; a dormant tie goes to the active one', () => {
    expect(m('mitre', false)).toMatchObject({ id: 'mitre-technique-prediction', how: 'inside-name' })
    expect(m('resume-selector', false)).toMatchObject({ id: 'ml-powered-resume-selector-using-naive-bayes' })
    expect(m('selector', false)).toBeNull() // one word that doesn't start a slug
  })
  it('a name that fits two active projects stays unmatched (anomaly-detection)', () => {
    expect(m('anomaly-detection', false)).toBeNull()
  })
  it('number: resolves only when exactly one repo has it; pr-0 and huge numbers never match', () => {
    expect(m('pr-359-preview')).toMatchObject({ id: 'marvin', how: 'number', ticket: 359 })
    expect(m('pr-100-x', false)).toBeNull() // both repos have #100
    expect(m('pr-0', false)).toBeNull()
    expect(m('pr-999999', false)).toBeNull()
  })
  it('content: G-Eskayo/<repo> in the files decides, but ~/.agents never counts', () => {
    put('pr-119-code-review-findings.md', 'Review of https://github.com/G-Eskayo/marvin/pull/119')
    expect(m('pr-119-code-review-findings.md')).toMatchObject({ id: 'marvin', how: 'content' })
    put('agents-only/run.md', 'run ~/.agents/venv/bin/python /Users/x/.agents/lib/x.py')
    expect(m('agents-only')).toBeNull()
  })
  it('content: a 1:1 tie is not a winner', () => {
    put('mixed/a.md', 'G-Eskayo/marvin and G-Eskayo/paper-dive')
    expect(m('mixed', false)).toBeNull()
  })
  it('docs phrase: needs two hits and twice any other project (seal speak 5 vs 2)', () => {
    expect(m('seal-speak-app-store-2026-10-20')).toMatchObject({ id: 'clarity-captions', how: 'docs', reason: "phrase 'seal speak' in its docs" })
    expect(m('seal-speak-app-store-2026-10-20', false)).toBeNull() // children never use the docs tier
    expect(m('settings-no-saved.png')).toBeNull() // one hit only
  })
  it('hostile names never throw and never match by accident', () => {
    for (const n of ['marvin-marvin-mobile', '../x', '..', '/etc/passwd', '.hidden', 'x'.repeat(300), '🦭🦭', '(((', '[a-z]+', '$(rm -rf ~)']) {
      expect(() => m(n)).not.toThrow()
    }
    expect(m('marvin-marvin-mobile')).toMatchObject({ id: 'marvin-mobile' })
    expect(m('[a-z]+')).toBeNull()
  })
  it('aliases from overrides.json make a name match', () => {
    expect(matchName(ctx({ overrides: { 'clarity-captions': { aliases: ['seal-speak'] } } }), 'seal-speak-ipad-2026-10-21')).toMatchObject({ id: 'clarity-captions', how: 'name' })
  })
})

describe('createDeliverables: placement, split folders and Unsorted', () => {
  const make = (over) => createDeliverables({ getContext: () => context(over), cachePath: path.join(home, '.claude', 'logs', 'outbox-matches.json') })
  beforeEach(() => {
    put('README.md', '# outbox readme')
    put('seal-speak-share-139-2026-10-20/a.png', 'png')
    put('marvin-402-files-viewer-2026-10-21/shot.png')
    put('ci-workflows/README.md')
    put('ci-workflows/clarity-captions/ci.yml')
    put('ci-workflows/marvin/ci.yml')
    put('migrations/anomaly-detection/x.md')
    put('migrations/paper-dive/x.md')
    put('usage_probe.py', 'print(1)')
    put('.DS_Store')
  })

  it('files whole items under their project, newest first, with reason and ticket chip', () => {
    const v = make().refresh()
    // newest first: the ci-workflows child has no date in its name, so its mtime (today) puts it first
    expect(v.byProject['clarity-captions'].map((e) => e.path)).toEqual(['ci-workflows/clarity-captions', 'seal-speak-share-139-2026-10-20'])
    expect(v.byProject['clarity-captions'][1]).toMatchObject({ isDir: true, count: 1, date: '2026-10-20', ticket: 139, how: 'docs', covers: ['seal-speak-share-139-2026-10-20/a.png'] })
    expect(v.byProject.marvin.map((e) => e.path)).toContain('marvin-402-files-viewer-2026-10-21')
  })
  it('splits an unmatched folder child by child; what is left stays under its folder in Unsorted', () => {
    const v = make().refresh()
    expect(v.byProject['paper-dive'].map((e) => e.path)).toEqual(['migrations/paper-dive'])
    expect(v.unsorted.whole.map((e) => e.path)).toEqual(['usage_probe.py'])
    expect(v.unsorted.leftovers).toEqual([
      { parent: 'ci-workflows', entries: [expect.objectContaining({ path: 'ci-workflows/README.md' })] },
      { parent: 'migrations', entries: [expect.objectContaining({ path: 'migrations/anomaly-detection' })] }
    ])
    expect(v.count).toBe(3)
  })
  it('skips the outbox README and dot files', () => {
    const v = make().refresh()
    const all = [...Object.values(v.byProject).flat(), ...v.unsorted.whole].map((e) => e.path)
    expect(all).not.toContain('README.md')
    expect(all.some((p) => p.includes('DS_Store'))).toBe(false)
  })
  it('a new process answers from the saved match map with no rescan (saved state first)', () => {
    make().refresh()
    rmSync(path.join(root, 'usage_probe.py'))
    const v = make().view() // not refreshed yet: still the saved map
    expect(v.unsorted.whole.map((e) => e.path)).toEqual(['usage_probe.py'])
  })
  it('refresh re-matches only the changed item (cached by name and mtime)', () => {
    const d = make()
    d.refresh()
    const before = JSON.parse(readFileSync(path.join(home, '.claude', 'logs', 'outbox-matches.json'), 'utf8'))
    put('marvin-402-files-viewer-2026-10-21/second.png')
    const t = new Date(Date.now() + 5000)
    utimesSync(path.join(root, 'marvin-402-files-viewer-2026-10-21'), t, t)
    d.refresh()
    const after = JSON.parse(readFileSync(path.join(home, '.claude', 'logs', 'outbox-matches.json'), 'utf8'))
    expect(after.items['marvin-402-files-viewer-2026-10-21'].summary.count).toBe(2)
    expect(after.items['usage_probe.py']).toEqual(before.items['usage_probe.py'])
  })
  it('a change deep inside a folder (no top-level mtime change) is picked up when the trigger names it', () => {
    const d = make()
    d.refresh()
    put('seal-speak-share-139-2026-10-20/deep/b.png')
    expect(d.refresh(['seal-speak-share-139-2026-10-20/deep/b.png']).byProject['clarity-captions'].find((e) => e.path.startsWith('seal')).count).toBe(2)
  })
  it('a catalog change re-matches everything', () => {
    const d = make()
    d.refresh()
    const v = createDeliverables({ getContext: () => context({ overrides: { 'clarity-captions': { aliases: ['usage-probe'] } } }), cachePath: path.join(home, '.claude', 'logs', 'outbox-matches.json') }).refresh()
    expect(v.byProject['clarity-captions'].map((e) => e.path)).toContain('usage_probe.py')
  })
  it('a corrupt match map rebuilds once', () => {
    mkdirSync(path.join(home, '.claude', 'logs'), { recursive: true })
    writeFileSync(path.join(home, '.claude', 'logs', 'outbox-matches.json'), '{nope')
    const v = make().view()
    expect(v.unsorted.whole.map((e) => e.path)).toEqual(['usage_probe.py'])
    expect(JSON.parse(readFileSync(path.join(home, '.claude', 'logs', 'outbox-matches.json'), 'utf8')).v).toBe(1)
  })
  it('an empty or missing outbox is an empty view, not an error', () => {
    rmSync(root, { recursive: true, force: true })
    expect(make().refresh()).toMatchObject({ byProject: {}, unsorted: { whole: [], leftovers: [] }, count: 0 })
  })
  it('a symlink pointing outside the outbox is never followed for content', () => {
    const outside = mkdtempSync(path.join(tmpdir(), 'outside-'))
    try {
      writeFileSync(path.join(outside, 'x.md'), 'G-Eskayo/paper-dive')
      symlinkSync(outside, path.join(root, 'linked'))
      const v = make().refresh()
      expect(v.byProject['paper-dive']?.map((e) => e.path) || []).not.toContain('linked')
    } finally {
      rmSync(outside, { recursive: true, force: true })
    }
  })
})

describe('search entries', () => {
  it('every file gets a path-words section, text files their text; past 200 files, paths only', () => {
    put('marvin-big/notes.md', '# Big notes\n\nthroughput')
    for (let i = 0; i < 201; i++) put(`marvin-huge/f${i}.md`, 'secret words')
    const d = createDeliverables({ getContext: () => context(), cachePath: path.join(home, 'm.json') })
    d.refresh()
    const docs = d.searchDocs()
    expect(docs.find((x) => x.path === 'outbox/marvin-big/notes.md' && x.content.includes('throughput'))).toMatchObject({ repo: 'marvin', kind: 'deliverable' })
    expect(docs.find((x) => x.path === 'outbox/marvin-big/')).toMatchObject({ isDir: true, content: '# marvin big' })
    expect(docs.filter((x) => x.path.startsWith('outbox/marvin-huge/f')).every((x) => !x.content.includes('secret'))).toBe(true)
    // cached per item: a second build reads no file again
    let reads = 0
    d.searchDocs({ readText: () => (reads++, null) })
    expect(reads).toBe(0)
  })
  it('unsorted items index under the Unsorted id, and HTML is searched without its tags or scripts', () => {
    put('page.html', '<html><script>evil()</script><p>Hello <b>world</b></p></html>')
    const docs = deliverableDocs([{ repo: UNSORTED_ID, entry: { path: 'page.html', isDir: false } }])
    const text = docs.find((x) => x.content.includes('Hello'))
    expect(text.repo).toBe(UNSORTED_ID)
    expect(text.content).not.toMatch(/evil|<b>/)
  })
})

describe('search ranking and the number tier over time', () => {
  it('a name hit outranks a long file that merely contains the words, and code is searched by name only', async () => {
    const { searchDocs } = await import('../electron/main/docs_search.js')
    put('seal-speak-app-store-2026-10-20/listing.md', '# Listing\n\nthe store page')
    put('marvin-notes/dump.json', JSON.stringify({ a: 'app store '.repeat(200) }))
    put('marvin-notes/patch.diff', 'app store '.repeat(500))
    const d = createDeliverables({ getContext: () => context(), cachePath: path.join(home, 'm.json') })
    d.refresh()
    const res = searchDocs({ docs: d.searchDocs() }, 'app store')
    expect(res[0].path).toMatch(/^outbox\/seal-speak-app-store-2026-10-20/)
    expect(res.some((r) => r.path === 'outbox/marvin-notes/patch.diff' && r.snippet.includes('app store app store'))).toBe(false)
  })
  it('board numbers seen once keep the number tier working before the boards load again', () => {
    put('pr-359-preview/index.html', '<p>x</p>')
    const cachePath = path.join(home, 'm.json')
    createDeliverables({ getContext: () => context(), cachePath }).refresh()
    const v = createDeliverables({ getContext: () => context({ maxNumber: {} }), cachePath }).refresh()
    expect(v.byProject.marvin.map((e) => e.path)).toContain('pr-359-preview')
  })
})

describe('outbox folder helpers (same guard as every outbox read)', () => {
  it('lists folders first, caps at 200 with a "more" count, hides dot files', () => {
    for (let i = 0; i < 205; i++) put(`big/f${String(i).padStart(3, '0')}.png`)
    put('big/sub/x.md')
    put('big/.hidden')
    const out = listOutboxDir('big')
    expect(out.entries[0]).toMatchObject({ type: 'dir', name: 'sub' })
    expect(out.entries.length).toBe(DIR_LIMIT)
    expect(out.more).toBe(6)
    expect(out.entries[1]).toMatchObject({ type: 'file', kind: 'image', label: 'Image' })
  })
  it('refuses traversal and absolute paths', () => {
    expect(() => listOutboxDir('../..')).toThrow()
    expect(() => listOutboxDir('/etc')).toThrow()
    expect(() => summarizeOutbox('../x')).toThrow()
    expect(outboxPreview('../../etc/passwd')).toBeNull()
  })
  it('summarizes a folder: count, first images as covers, kinds', () => {
    put('f/b.png')
    put('f/a.md', '# A')
    put('f/sub/c.png')
    expect(summarizeOutbox('f')).toMatchObject({ isDir: true, count: 3, covers: ['f/b.png', 'f/sub/c.png'], kinds: ['Markdown', 'Image'] })
    expect(summarizeOutbox('missing')).toBeNull()
  })
  it('previews a markdown file from its first 2 KB only', () => {
    put('f/listing.md', `# Seal Speak 1.0\n\nBuilt from docs.\n${'x'.repeat(5_000_000)}`)
    expect(outboxPreview('f/listing.md')).toEqual({ title: 'Seal Speak 1.0', text: expect.stringContaining('Built from docs.') })
    expect(outboxPreview('f/b.png')).toBeNull()
  })
  it('the sandbox really is a temp HOME', () => {
    expect(homedir()).toBe(home)
  })
})

import { describe, it, expect, vi } from 'vitest'

vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))
vi.mock('../webhook-server/failure_log.js', () => ({ recordFailure: vi.fn() }))
vi.mock('../webhook-server/rebase_status.js', () => ({ writeRebaseStatus: vi.fn(), readRebaseStatus: vi.fn(() => ({})) }))

import { touchesUi, uiFiles, hasImage, assertUiEvidence, globToRegExp, DEFAULT_UI_PATTERNS, imageUrls, unpinnedImages, imageShas } from '../webhook-server/ui_evidence.js'
import { mergePr } from '../webhook-server/merge.js'
import { describePrState } from '../src/lib/prState.js'

// marvin #374 (2026-10-09): the owner's hard rule. Anything that changes how an app looks carries images, so he can
// see what he is approving. Several clarity-captions UI PRs merged with none, and he found unapproved design changes
// on his phone.

describe('which changed files are UI', () => {
  it('matches the defaults: SwiftUI views, asset catalogs, string catalogs, web UI', () => {
    for (const f of [
      'Apps/Spike/Sources/Assets.xcassets/LaunchMark.imageset/icon-light.png',
      'Apps/Spike/Sources/Localizable.xcstrings',
      'Apps/Spike/Sources/SettingsSheet.swift'.replace('SettingsSheet', 'SettingsView'),
      'App/Views/Home.swift',
      'Main.storyboard',
      'dashboard/src/components/PrCard.jsx',
      'site/privacy.html',
      'styles/app.css'
    ]) expect(touchesUi([f]), f).toBe(true)
  })

  it('leaves logic, tests, docs and the Electron main process alone', () => {
    expect(touchesUi([
      'Packages/CaptionCore/Sources/CaptionCore/CaptionSessionController.swift',
      'Packages/CaptionCore/Tests/CaptionCoreTests/FooTests.swift',
      'docs/adr/0022-saved.md',
      'dashboard/electron/main/mr_review.js',
      'dashboard/webhook-server/merge.js',
      'lib/run_ticket.py'
    ])).toBe(false)
  })

  it('leaves the dashboard\'s helper logic in src/lib alone: it changes no screen (#389 was flagged for a capture helper)', () => {
    expect(touchesUi(['dashboard/src/lib/screenshot_capture.js', 'dashboard/src/lib/prState.js', 'dashboard/src/lib/linkify.js'])).toBe(false)
    expect(touchesUi(['dashboard/src/lib/markdown_images.test.js'])).toBe(false)
  })

  it('still counts every dashboard screen: components, the app shell, styles and the entry point', () => {
    for (const f of ['dashboard/src/components/PrCard.jsx', 'dashboard/src/components/sub/thing.js', 'dashboard/src/App.jsx',
      'dashboard/src/index.css', 'dashboard/src/main.jsx', 'dashboard/src/assets/logo.svg', 'dashboard/src/lib/Widget.jsx'])
      expect(touchesUi([f]), f).toBe(true)
  })

  it('adds a project\'s own patterns to the defaults', () => {
    const files = ['Apps/Spike/Sources/SettingsSheet.swift', 'Packages/CaptionCore/Tests/X.swift']
    expect(touchesUi(files)).toBe(false)
    expect(touchesUi(files, ['Apps/**/*.swift'])).toBe(true)
    expect(uiFiles(files, ['Apps/**/*.swift'])).toEqual(['Apps/Spike/Sources/SettingsSheet.swift'])
  })

  it('globs: ** crosses folders, * does not, dots are literal', () => {
    expect(globToRegExp('Apps/**/*.swift').test('Apps/Spike/Sources/A.swift')).toBe(true)
    expect(globToRegExp('Apps/*.swift').test('Apps/Spike/A.swift')).toBe(false)
    expect(globToRegExp('*.css').test('acss')).toBe(false)
    expect(globToRegExp('**/*.xcstrings').test('Localizable.xcstrings')).toBe(true)
  })

  it('tolerates junk input', () => {
    expect(touchesUi(null)).toBe(false)
    expect(touchesUi([null, undefined, 42, ''])).toBe(false)
    expect(touchesUi(['Apps/A.swift'], 'not-a-list')).toBe(false)
    expect(DEFAULT_UI_PATTERNS.length).toBeGreaterThan(0)
  })
})

describe('does the PR body show an image', () => {
  it('counts markdown and HTML images, including GitHub attachments', () => {
    expect(hasImage('![](docs/images/pr/83.png)')).toBe(true)
    expect(hasImage('Settings:\n\n![Settings, dark](https://raw.githubusercontent.com/o/r/b/x.png)')).toBe(true)
    expect(hasImage('<img width="300" alt="x" src="https://github.com/user-attachments/assets/abc" />')).toBe(true)
    expect(hasImage("<IMG SRC='a.png'>")).toBe(true)
  })

  it('does not count links, words or empty images', () => {
    expect(hasImage('see [the screenshot](x.png)')).toBe(false)
    expect(hasImage('https://example.com/shot.png')).toBe(false)
    expect(hasImage('No screenshots could be captured.')).toBe(false)
    expect(hasImage('![]()')).toBe(false)
    expect(hasImage('<img alt="nothing">')).toBe(false)
    expect(hasImage('`![code](x.png)` in backticks is still markdown')).toBe(true)
    expect(hasImage(null)).toBe(false)
  })
})

const PR = 'https://github.com/G-Eskayo/clarity-captions/pull/95'
function ghView({ files = [], body = '', fails = false, head = HEAD, compare = {}, commitDates = {}, prCommits = [] } = {}) {
  return vi.fn(async (cmd, args) => {
    // An image commit in another repo (the instance repo): only its date is asked for, from that repo.
    const own = /^repos\/([^/]+\/[^/]+)\/commits\/([0-9a-f]{40})$/.exec(args?.[1] || '')
    if (cmd === 'gh' && args[0] === 'api' && own) {
      const key = `${own[1]}@${own[2]}`
      if (!(key in commitDates)) throw Object.assign(new Error('Command failed: gh api'), { stderr: 'HTTP 422: No commit found' })
      return { stdout: JSON.stringify({ sha: own[2], commit: { committer: { date: commitDates[key] } } }), stderr: '' }
    }
    if (cmd === 'gh' && args[0] === 'api' && args.some((a) => /\/pulls\/\d+\/commits/.test(a))) {
      return { stdout: JSON.stringify(prCommits.map(([sha, date]) => ({ sha, commit: { committer: { date } } }))), stderr: '' }
    }
    if (cmd === 'gh' && args[1] === 'view' && args.includes('files,body,headRefOid')) {
      if (fails) throw Object.assign(new Error('Command failed: gh pr view'), { stderr: 'HTTP 502: Bad Gateway' })
      return { stdout: JSON.stringify({ files: files.map((path) => ({ path })), body, headRefOid: head }), stderr: '' }
    }
    if (cmd === 'gh' && args[0] === 'api' && /\/compare\//.test(args[1] || '')) {
      const base = args[1].split('/compare/')[1].split('...')[0]
      if (!(base in compare)) throw Object.assign(new Error('Command failed: gh api'), { stderr: 'HTTP 404: No common ancestor' })
      return { stdout: JSON.stringify(compare[base]), stderr: '' }
    }
    return { stdout: JSON.stringify({ baseRefName: 'main', isDraft: false }), stderr: '' }
  })
}

const HEAD = 'f'.repeat(40)
const OLD = '1c7c6a786452732c40d10230ea92a84c9231de2e'
const pinned = (sha, name = 's') => `![${name}](https://raw.githubusercontent.com/G-Eskayo/clarity-captions/${sha}/docs/${name}.png)`

describe('which images are pinned to a commit (marvin #733)', () => {
  it('finds markdown and HTML image targets', () => {
    expect(imageUrls('![a](https://x/a.png) <img src="https://x/b.png"> [link](https://x/c.png)')).toEqual(['https://x/a.png', 'https://x/b.png'])
  })

  it('a branch-name link is unpinned: GitHub and the dashboard keep serving the old image after a retake (#171)', () => {
    const body = '![a](https://github.com/G-Eskayo/clarity-captions/blob/feature/37-53/docs/a.png?raw=true) ![r](a.png)'
    expect(unpinnedImages(body)).toEqual(['https://github.com/G-Eskayo/clarity-captions/blob/feature/37-53/docs/a.png?raw=true', 'a.png'])
  })

  it('a full commit SHA, or a GitHub upload (never changes), is pinned', () => {
    const body = pinned(OLD) + ' ![u](https://github.com/user-attachments/assets/8f1c2d3e-aaaa-bbbb-cccc-1234567890ab)' +
      ' ![v](https://private-user-images.githubusercontent.com/1/2-3.png?jwt=x) ![b](https://github.com/o/r/blob/' + OLD + '/a.png?raw=true)'
    expect(unpinnedImages(body)).toEqual([])
    expect(imageShas(body)).toEqual([OLD])
  })

  it('a short SHA or a 40-letter word that is not hex is not a pin', () => {
    expect(unpinnedImages('![a](https://raw.githubusercontent.com/o/r/1c7c6a7/a.png)')).toHaveLength(1)
    expect(imageShas('![a](https://raw.githubusercontent.com/o/r/' + 'z'.repeat(40) + '/a.png)')).toEqual([])
  })
})

describe('the approve gate refuses unpinned or stale images (marvin #733)', () => {
  const ui = ['Apps/A/SettingsView.swift']

  it('unpinned images on a UI change: IMAGES_UNPINNED, naming them', async () => {
    const p = assertUiEvidence(PR, ghView({ files: ui, body: '![a](https://github.com/o/r/blob/main/a.png?raw=true)' }))
    await expect(p).rejects.toMatchObject({ payload: { code: 'IMAGES_UNPINNED', message: expect.stringContaining('blob/main/a.png') } })
  })

  it('images pinned to a commit after which a UI file changed: IMAGES_STALE, naming the file', async () => {
    const exec = ghView({ files: ui, body: pinned(OLD), compare: { [OLD]: { files: [{ filename: 'Apps/A/SettingsView.swift' }, { filename: 'lib/x.py' }] } } })
    await expect(assertUiEvidence(PR, exec)).rejects.toMatchObject({
      payload: { code: 'IMAGES_STALE', message: expect.stringContaining('SettingsView.swift') }
    })
  })

  it('only logic changed since the images: still current (#155: no new screenshots needed)', async () => {
    const exec = ghView({ files: ui, body: pinned(OLD), compare: { [OLD]: { files: [{ filename: 'Packages/Core/Logic.swift' }] } } })
    await expect(assertUiEvidence(PR, exec)).resolves.toBeUndefined()
  })

  it('images pinned to the head commit need no comparison', async () => {
    const exec = ghView({ files: ui, body: pinned(HEAD) })
    await expect(assertUiEvidence(PR, exec)).resolves.toBeUndefined()
    expect(exec.mock.calls.some((c) => c[0] === 'gh' && c[1][0] === 'api')).toBe(false)
  })

  it('one stale set among several is enough to refuse', async () => {
    const NEW = 'a'.repeat(40)
    const exec = ghView({ files: ui, body: pinned(NEW, 'n') + pinned(OLD, 'o'),
      compare: { [NEW]: { files: [] }, [OLD]: { files: [{ filename: 'Apps/A/SettingsView.swift' }] } } })
    await expect(assertUiEvidence(PR, exec)).rejects.toMatchObject({ payload: { code: 'IMAGES_STALE' } })
  })

  it('a commit GitHub can\'t compare (rewritten history) fails closed', async () => {
    await expect(assertUiEvidence(PR, ghView({ files: ui, body: pinned(OLD) }))).rejects.toMatchObject({ payload: { code: 'UI_EVIDENCE_UNCHECKED' } })
  })

  it('a non-UI PR is never asked about its images', async () => {
    await expect(assertUiEvidence(PR, ghView({ files: ['lib/x.py'], body: '![a](a.png)' }))).resolves.toBeUndefined()
  })
})

describe('images kept in another repo, like MARVIN\'s instance repo (marvin #773)', () => {
  // MARVIN's PR images live in G-Eskayo/marvin-instance (ADR 0071), so their commit never exists in the PR's repo.
  // #766 was refused with "couldn't check whether the images (taken at 94d88fb) are current" because the gate asked
  // the marvin repo for an instance-repo commit.
  const MPR = 'https://github.com/G-Eskayo/marvin/pull/766'
  const IMG = '94d88fb246160cd7dcc5a3a928a59adaf32cbb13'
  const C1 = '1'.repeat(40), C2 = '2'.repeat(40)
  const instancePinned = (sha) => `![s](https://raw.githubusercontent.com/G-Eskayo/marvin-instance/${sha}/docs/screenshots/x/s.png)`
  const uiM = ['dashboard/src/components/PrCard.jsx']

  it('never asks the PR\'s repo about an instance-repo commit', async () => {
    const exec = ghView({ files: uiM, body: instancePinned(IMG), head: C2,
      commitDates: { [`G-Eskayo/marvin-instance@${IMG}`]: '2026-10-29T20:00:00Z' },
      prCommits: [[C1, '2026-10-29T19:00:00Z'], [C2, '2026-10-29T19:30:00Z']] })
    await expect(assertUiEvidence(MPR, exec)).resolves.toBeUndefined()
    expect(exec.mock.calls.some((c) => (c[1]?.[1] || '').includes(`marvin/compare/${IMG}`))).toBe(false)
  })

  it('images taken after the last commit are current, with no compare needed', async () => {
    const exec = ghView({ files: uiM, body: instancePinned(IMG), head: C2,
      commitDates: { [`G-Eskayo/marvin-instance@${IMG}`]: '2026-10-29T20:00:00Z' },
      prCommits: [[C1, '2026-10-29T19:00:00Z'], [C2, '2026-10-29T19:30:00Z']] })
    await expect(assertUiEvidence(MPR, exec)).resolves.toBeUndefined()
  })

  it('a look-changing commit after the images makes them stale, naming the file', async () => {
    const exec = ghView({ files: uiM, body: instancePinned(IMG), head: C2,
      commitDates: { [`G-Eskayo/marvin-instance@${IMG}`]: '2026-10-29T19:15:00Z' },
      prCommits: [[C1, '2026-10-29T19:00:00Z'], [C2, '2026-10-29T19:30:00Z']],
      compare: { [C1]: { files: [{ filename: 'dashboard/src/components/PrCard.jsx' }] } } })
    await expect(assertUiEvidence(MPR, exec)).rejects.toMatchObject({
      payload: { code: 'IMAGES_STALE', message: expect.stringContaining('PrCard.jsx') }
    })
  })

  it('only logic changed after the images: still current', async () => {
    const exec = ghView({ files: uiM, body: instancePinned(IMG), head: C2,
      commitDates: { [`G-Eskayo/marvin-instance@${IMG}`]: '2026-10-29T19:15:00Z' },
      prCommits: [[C1, '2026-10-29T19:00:00Z'], [C2, '2026-10-29T19:30:00Z']],
      compare: { [C1]: { files: [{ filename: 'dashboard/webhook-server/merge.js' }] } } })
    await expect(assertUiEvidence(MPR, exec)).resolves.toBeUndefined()
  })

  it('images older than every commit of the PR are stale when the PR changes the look', async () => {
    const exec = ghView({ files: uiM, body: instancePinned(IMG), head: C2,
      commitDates: { [`G-Eskayo/marvin-instance@${IMG}`]: '2026-10-28T10:00:00Z' },
      prCommits: [[C1, '2026-10-29T19:00:00Z'], [C2, '2026-10-29T19:30:00Z']] })
    await expect(assertUiEvidence(MPR, exec)).rejects.toMatchObject({ payload: { code: 'IMAGES_STALE' } })
  })

  it('an image commit its own repo can\'t find fails closed, naming that repo', async () => {
    const exec = ghView({ files: uiM, body: instancePinned(IMG), head: C2, prCommits: [[C2, '2026-10-29T19:30:00Z']] })
    await expect(assertUiEvidence(MPR, exec)).rejects.toMatchObject({
      payload: { code: 'UI_EVIDENCE_UNCHECKED', message: expect.stringContaining('marvin-instance') }
    })
  })

  it('same-repo images keep the direct compare', async () => {
    const exec = ghView({ files: ['Apps/A/SettingsView.swift'], body: pinned(OLD), compare: { [OLD]: { files: [] } } })
    await expect(assertUiEvidence(PR, exec)).resolves.toBeUndefined()
    expect(exec.mock.calls.some((c) => (c[1]?.[1] || '').includes(`clarity-captions/compare/${OLD}`))).toBe(true)
  })
})

describe('the approve gate refuses a UI change with no image', () => {
  it('UI change with an image: ok', async () => {
    await expect(assertUiEvidence(PR, ghView({ files: ['Apps/A/SettingsView.swift'], body: pinned(HEAD) }))).resolves.toBeUndefined()
  })

  it('UI change without an image: NO_UI_EVIDENCE, naming the files', async () => {
    const p = assertUiEvidence(PR, ghView({ files: ['Apps/A/SettingsView.swift', 'x.md'], body: 'Could not capture screenshots.' }))
    await expect(p).rejects.toMatchObject({ payload: { code: 'NO_UI_EVIDENCE', action: 'escalate', retryable: false } })
    await expect(assertUiEvidence(PR, ghView({ files: ['Apps/A/SettingsView.swift'] }))).rejects.toMatchObject({
      payload: { message: expect.stringContaining('SettingsView.swift') }
    })
  })

  it('non-UI change without an image: ok', async () => {
    await expect(assertUiEvidence(PR, ghView({ files: ['lib/x.py', 'docs/a.md'] }))).resolves.toBeUndefined()
  })

  it('uses the project\'s own patterns', async () => {
    const exec = ghView({ files: ['Apps/Spike/Sources/MorphingControl.swift'] })
    await expect(assertUiEvidence(PR, exec)).resolves.toBeUndefined()
    await expect(assertUiEvidence(PR, exec, ['Apps/**/*.swift'])).rejects.toMatchObject({ payload: { code: 'NO_UI_EVIDENCE' } })
  })

  it('fails closed when GitHub cannot be asked: a refused Approve costs a click, an unseen UI change breaks the rule', async () => {
    await expect(assertUiEvidence(PR, ghView({ fails: true }))).rejects.toMatchObject({ payload: { code: 'UI_EVIDENCE_UNCHECKED' } })
    await expect(assertUiEvidence(PR, vi.fn().mockResolvedValue({ stdout: 'not json' }))).rejects.toMatchObject({ payload: { code: 'UI_EVIDENCE_UNCHECKED' } })
  })

  it('mergePr refuses before any gate work or merge', async () => {
    const exec = ghView({ files: ['dashboard/src/components/PrCard.jsx'], body: 'no pictures' })
    const shouldGate = vi.fn()
    await expect(mergePr('https://github.com/G-Eskayo/marvin/pull/95', exec, () => Promise.resolve(), () => {}, shouldGate))
      .rejects.toMatchObject({ payload: { code: 'NO_UI_EVIDENCE' } })
    expect(shouldGate).not.toHaveBeenCalled()
    expect(exec.mock.calls.some((c) => c[1]?.[1] === 'merge')).toBe(false)
  })
})

describe('the review card says Needs images and offers no Approve', () => {
  it('needs-images state', () => {
    const s = describePrState({ needsImages: { files: ['Apps/A/SettingsView.swift'] } })
    expect(s.kind).toBe('needs-images')
    expect(s.headline).toMatch(/needs images/i)
    expect(s.approve).toBe('hidden')
    expect(s.detail).toContain('SettingsView.swift')
  })
})

describe('the PR list flags UI changes without images', async () => {
  const { listPipelinePrs } = await import('../electron/main/mr_review.js')
  const { readUiPaths } = await import('../electron/main/profiles.js')
  const { mkdtempSync, writeFileSync, rmSync } = await import('fs')
  const { tmpdir } = await import('os')
  const path = (await import('path')).default
  const pr = (n, files, body) => ({ number: n, title: `t${n}`, url: `https://github.com/G-Eskayo/clarity-captions/pull/${n}`, repo: 'G-Eskayo/clarity-captions', body, files: files.map((p) => ({ path: p })) })

  it('needsImages only for a UI change with no image, using the project\'s own paths', async () => {
    const prs = [
      pr(1, ['Apps/Spike/Sources/SettingsSheet.swift'], 'no pictures'),
      pr(2, ['Apps/Spike/Sources/SettingsSheet.swift'], '![s](https://raw.githubusercontent.com/G-Eskayo/clarity-captions/1c7c6a786452732c40d10230ea92a84c9231de2e/docs/s.png)'),
      pr(3, ['lib/x.py'], 'nothing'),
      { ...pr(4, [], 'x'), files: undefined }
    ]
    const out = await listPipelinePrs(async () => prs, { uiPathsFor: (repo) => (repo === 'G-Eskayo/clarity-captions' ? ['Apps/**/*.swift'] : []) })
    expect(out.map((p) => p.needsImages)).toEqual([{ files: ['Apps/Spike/Sources/SettingsSheet.swift'] }, null, null, null])
  })

  it('unpinned images also need fixing, with the reason on the card (marvin #733)', async () => {
    const body = '![a](https://github.com/G-Eskayo/clarity-captions/blob/feature/x/a.png?raw=true)'
    const out = await listPipelinePrs(async () => [pr(1, ['Apps/A/HomeView.swift'], body)], {})
    expect(out[0].needsImages).toMatchObject({ files: ['Apps/A/HomeView.swift'], unpinned: [expect.stringContaining('blob/feature/x')] })
    const s = describePrState({ needsImages: out[0].needsImages })
    expect(s.approve).toBe('hidden')
    expect(s.detail).toMatch(/pinned to a commit/i)
  })

  it('a broken profile lookup never hides or flags a PR wrongly', async () => {
    const out = await listPipelinePrs(async () => [pr(1, ['Apps/A/HomeView.swift'], 'none')], { uiPathsFor: () => { throw new Error('boom') } })
    expect(out[0].needsImages).toEqual({ files: ['Apps/A/HomeView.swift'] })
  })

  it('reads evidence.ui_paths from the project profile', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'profiles-'))
    try {
      writeFileSync(path.join(dir, 'cc.json'), JSON.stringify({ repo: 'G-Eskayo/clarity-captions', evidence: { ui_paths: ['Apps/**/*.swift', 7] } }))
      writeFileSync(path.join(dir, 'broken.json'), '{nope')
      expect(readUiPaths('G-Eskayo/clarity-captions', dir)).toEqual(['Apps/**/*.swift'])
      expect(readUiPaths('G-Eskayo/other', dir)).toEqual([])
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

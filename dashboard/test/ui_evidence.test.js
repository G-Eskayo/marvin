import { describe, it, expect, vi } from 'vitest'

vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))
vi.mock('../webhook-server/failure_log.js', () => ({ recordFailure: vi.fn() }))
vi.mock('../webhook-server/rebase_status.js', () => ({ writeRebaseStatus: vi.fn(), readRebaseStatus: vi.fn(() => ({})) }))

import { touchesUi, uiFiles, hasImage, assertUiEvidence, globToRegExp, DEFAULT_UI_PATTERNS } from '../webhook-server/ui_evidence.js'
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
function ghView({ files = [], body = '', fails = false } = {}) {
  return vi.fn(async (cmd, args) => {
    if (cmd === 'gh' && args[1] === 'view' && args.includes('files,body')) {
      if (fails) throw Object.assign(new Error('Command failed: gh pr view'), { stderr: 'HTTP 502: Bad Gateway' })
      return { stdout: JSON.stringify({ files: files.map((path) => ({ path })), body }), stderr: '' }
    }
    return { stdout: JSON.stringify({ baseRefName: 'main', isDraft: false }), stderr: '' }
  })
}

describe('the approve gate refuses a UI change with no image', () => {
  it('UI change with an image: ok', async () => {
    await expect(assertUiEvidence(PR, ghView({ files: ['Apps/A/SettingsView.swift'], body: '![s](a.png)' }))).resolves.toBeUndefined()
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
      pr(2, ['Apps/Spike/Sources/SettingsSheet.swift'], '![s](a.png)'),
      pr(3, ['lib/x.py'], 'nothing'),
      { ...pr(4, [], 'x'), files: undefined }
    ]
    const out = await listPipelinePrs(async () => prs, { uiPathsFor: (repo) => (repo === 'G-Eskayo/clarity-captions' ? ['Apps/**/*.swift'] : []) })
    expect(out.map((p) => p.needsImages)).toEqual([{ files: ['Apps/Spike/Sources/SettingsSheet.swift'] }, null, null, null])
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

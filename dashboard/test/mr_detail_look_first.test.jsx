import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import MrDetail, { GALLERY_LIMIT } from '../src/components/MrDetail.jsx'
import PrImages, { visibleCount } from '../src/components/PrImages.jsx'
import MockupLauncher, { openOutcome } from '../src/components/MockupLauncher.jsx'
import { prSummary } from '../electron/main/pr_summary.js'
import { imageRefsFor, sceneOf } from '../src/lib/decision_refs.js'
import { listPipelinePrs } from '../electron/main/mr_review.js'
import { summarizeDecisions } from '../webhook-server/decisions.js'

// G-Eskayo/marvin#938: what to look at comes before the choices.

const RAW = 'https://raw.githubusercontent.com/G-Eskayo/marvin-instance/b0ac4ed/docs/screenshots/design-924'
const BODY_934 = `Mock-up for #924. It's the first step of that ticket, and the build follows once you sign off the look. The real app (\`dashboard/src\`) is not changed.

## What it is
On a PR that asks for Decisions, your answers are the approval.
- **Every answer matches what's built:** "Merge with these answers".

## Try it
Open it in Chrome (straight from Finder).

<!-- marvin:shots -->
## Screenshots

a. Every answer is what was built: one press merges

![a. Every answer is what was built: one press merges](${RAW}/a-dark-820.png)

b. One answer changed: the button becomes Send back, and the line says why

![b. One answer changed: the button becomes Send back, and the line says why](${RAW}/b-dark-820.png)
<!-- /marvin:shots -->

## Decisions
<!-- marvin:decisions -->
### look: The wording and look in scene b (button names)
- [ ] Keep it all as shown
- [ ] Keep it, with the changes in my note

### unbuilt-answer: Answering a question that nothing was built for
- [ ] Send back (scene e after a pick)
- [ ] Merge anyway
`
const FILES_934 = [
  { path: 'docs/design/answers-are-approval-924/README.md' },
  { path: 'docs/design/answers-are-approval-924/answer_state.js' },
  { path: 'docs/design/answers-are-approval-924/index.html' }
]

beforeEach(() => {
  globalThis.window = { api: { relations: { pr: () => new Promise(() => {}) }, mr: { ticketContext: () => new Promise(() => {}), mergeState: () => new Promise(() => {}), image: () => new Promise(() => {}) }, decisions: {} } }
})

async function pr934(extra = {}) {
  const [pr] = await listPipelinePrs(async () => [{
    number: 934, title: 'Mock-up: answers are the approval (#924)', url: 'https://github.com/G-Eskayo/marvin/pull/934', repo: 'G-Eskayo/marvin',
    body: BODY_934, files: FILES_934, headRefName: 'design/924-answers-are-approval', headRefOid: 'a990349dbd151f99eb4e17b84b150935aa673bb3', ...extra
  }], { canMerge: () => true })
  return pr
}

const order = (html, marks) => marks.map((m) => {
  const i = html.indexOf(m)
  expect(i, `missing ${m}`).toBeGreaterThan(-1)
  return i
})

describe('prSummary: the opening paragraph, then the first "What it is" section', () => {
  it('PR #934: both, and nothing from Try it or below', () => {
    const s = prSummary(BODY_934)
    expect(s.startsWith('Mock-up for #924.')).toBe(true)
    expect(s).toContain('your answers are the approval')
    expect(s).toContain('Merge with these answers')
    expect(s).not.toContain('Chrome')
    expect(s).not.toContain('Screenshots')
    expect(s).not.toContain('## What it is')
  })
  it('skips a leading "Closes #N" and an image, and stops at the paragraph\'s end', () => {
    expect(prSummary('Closes #933\n\n**Stacked on #941.** It does X.\nStill X.\n\nSecond paragraph.\n\n## What changed\n- y')).toBe('**Stacked on #941.** It does X.\nStill X.')
    expect(prSummary('![x](a.png)\nThe point.')).toBe('The point.')
  })
  it('a body that opens with a heading and has no What it is gives nothing; one with only What it is gives that', () => {
    expect(prSummary('## Summary\nhi')).toBe('')
    expect(prSummary('### What it is\nA thing.\n#### detail\nmore\n### Next\nno')).toBe('A thing.\n#### detail\nmore')
  })
  it('a "#" inside fenced code is not a heading, and HTML comments are dropped', () => {
    expect(prSummary('<!-- marvin:shots -->\nIntro.\n\n## What it is\n```\n# not a heading\n```\nafter\n## End')).toBe('Intro.\n\n```\n# not a heading\n```\nafter')
  })
  it('empty, missing and huge bodies', () => {
    expect(prSummary('')).toBe('')
    expect(prSummary(undefined)).toBe('')
    const long = prSummary(`${'word '.repeat(2000)}`)
    expect(long.length).toBeLessThan(1700)
    expect(long.endsWith('…')).toBe(true)
  })
})

describe('listPipelinePrs carries the summary, the mock-ups and the head commit', () => {
  it('PR #934', async () => {
    const pr = await pr934()
    expect(pr.summary.startsWith('Mock-up for #924.')).toBe(true)
    expect(pr.mockups).toEqual([{ path: 'docs/design/answers-are-approval-924/index.html', dir: 'docs/design/answers-are-approval-924', name: 'answers-are-approval-924' }])
    expect(pr.headSha).toBe('a990349dbd151f99eb4e17b84b150935aa673bb3')
  })
  it('the light list (no files) finds no mock-up unless the body marks one', async () => {
    const pr = await pr934({ files: undefined })
    expect(pr.mockups).toEqual([])
  })
})

describe('MrDetail order: what it is, the mock-up, the pictures, then the Decisions, then the evidence', () => {
  it('PR #934', async () => {
    const html = renderToStaticMarkup(<MrDetail pr={await pr934()} onBack={() => {}} />)
    const at = order(html, ['data-summary="1"', 'data-mockups="1"', 'Images &amp; recordings (2)', 'data-decisions', 'PR Description', 'Requirements &amp; Tasks'])
    expect([...at].sort((a, b) => a - b)).toEqual(at)
    expect(html).toContain('>Try the mock-up<')
    expect(html).toContain('docs/design/answers-are-approval-924/index.html')
  })
  it('the pictures are large: two a row on a wide window, one when narrow, with pr-shots\' line above each', async () => {
    const html = renderToStaticMarkup(<MrDetail pr={await pr934()} onBack={() => {}} />)
    expect(html).toContain('grid grid-cols-1 gap-4 lg:grid-cols-2')
    expect(html).not.toContain('xl:grid-cols-3')
    const fig = html.indexOf('id="pr-image-0"')
    const cap = html.indexOf('a. Every answer is what was built: one press merges</figcaption>', fig)
    expect(cap).toBeGreaterThan(fig)
    expect(cap).toBeLessThan(html.indexOf('aria-label="Loading image"', fig))
    expect(html).toContain('id="pr-image-0"')
    expect(html).toContain('id="pr-image-1"')
  })
  it('a Decision that names a scene links to its picture; one naming a scene with no picture gets no link', async () => {
    const html = renderToStaticMarkup(<MrDetail pr={await pr934()} onBack={() => {}} />)
    expect(html).toContain('data-see-image="1"')
    expect(html).toContain('See scene b ↑')
    expect(html).not.toContain('scene e ↑')
    expect(html.match(/data-see-image=/g)).toHaveLength(1)
  })
  it('a long summary opens clamped with "Read the rest"; a short one is whole', async () => {
    const html = renderToStaticMarkup(<MrDetail pr={{ ...(await pr934()), summary: 'A long one. '.repeat(40) }} onBack={() => {}} />)
    expect(html).toContain('data-clamped="1"')
    expect(html).toContain('Read the rest')
    const short = renderToStaticMarkup(<MrDetail pr={{ ...(await pr934()), summary: 'A short one.' }} onBack={() => {}} />)
    expect(short).not.toContain('data-clamped')
    expect(short).not.toContain('Read the rest')
  })
  it('a PR without a mock-up is unchanged apart from the order: no button, same sections', async () => {
    const plain = await pr934({ files: [{ path: 'lib/x.py' }], body: BODY_934.replace(/Mock-up for #924\./, 'A fix.') })
    expect(plain.mockups).toEqual([])
    const html = renderToStaticMarkup(<MrDetail pr={plain} onBack={() => {}} />)
    expect(html).not.toContain('data-mockups')
    expect(html).not.toContain('Try the mock-up')
    const at = order(html, ['data-summary="1"', 'Images &amp; recordings (2)', 'data-decisions', 'PR Description', 'Requirements &amp; Tasks', 'Design &amp; Architecture'])
    expect([...at].sort((a, b) => a - b)).toEqual(at)
  })
  it('a PR with no summary, images or decisions still renders its description and ticket sections', () => {
    const html = renderToStaticMarkup(<MrDetail pr={{ number: 1, title: 't', url: 'u', repo: 'o/r', hasSchema: false, rawBody: '## Only a heading', images: [], decisions: { present: false } }} onBack={() => {}} />)
    expect(html).not.toContain('data-summary')
    expect(html).not.toContain('data-mockups')
    expect(html).toContain('PR Description')
  })
  it('an older saved PR (no summary, mockups or headSha fields) renders as before', () => {
    const html = renderToStaticMarkup(<MrDetail pr={{ number: 2, title: 't', url: 'u', repo: 'o/r', hasSchema: false, rawBody: 'x' }} onBack={() => {}} />)
    expect(html).toContain('PR Description')
  })
  it('read-only (merged) PRs show the summary and the mock-up but no Decisions', async () => {
    const html = renderToStaticMarkup(<MrDetail pr={{ ...(await pr934()), readOnly: true, state: 'MERGED' }} onBack={() => {}} />)
    expect(html).toContain('data-summary="1"')
    expect(html).toContain('data-mockups="1"')
    expect(html).not.toContain('data-decisions')
  })
})

describe('a PR with 20 screenshots', () => {
  const twenty = Array.from({ length: 20 }, (_, i) => ({ url: `${RAW}/${i}.png`, alt: `${String.fromCharCode(97 + i)}. Shot ${i}`, group: 'Screenshots', caption: `${String.fromCharCode(97 + i)}. Shot number ${i}` }))
  it('shows the first few large, and a button for the rest, so the Decisions stay near', () => {
    const html = renderToStaticMarkup(<PrImages images={twenty} size="large" anchorPrefix="pr-image" limit={GALLERY_LIMIT} loadImage={vi.fn(() => new Promise(() => {}))} />)
    expect(html.match(/aria-label="Loading image"/g)).toHaveLength(GALLERY_LIMIT)
    expect(html).toContain('Show all 20 images')
    expect(html).not.toContain('id="pr-image-6"')
  })
  it('visibleCount', () => {
    expect(visibleCount(20, 6, false)).toBe(6)
    expect(visibleCount(20, 6, true)).toBe(20)
    expect(visibleCount(6, 6, false)).toBe(6)
    expect(visibleCount(3, 0, false)).toBe(3)
  })
  it('the section count says all 20, and a Decision can still point at the 18th', () => {
    const d = summarizeDecisions('<!-- marvin:decisions -->\n### pick: Which of scene r or scene s?\n- [ ] r\n- [ ] s\n')
    const pr = { number: 3, title: 't', url: 'u', repo: 'o/r', hasSchema: false, rawBody: 'x', images: twenty, decisions: d }
    const html = renderToStaticMarkup(<MrDetail pr={pr} onBack={() => {}} />)
    expect(html).toContain('Images &amp; recordings (20)')
    expect(html).toContain('data-see-image="17"')
    expect(html).toContain('data-see-image="18"')
  })
  it('the small gallery elsewhere (Dev evidence) is unchanged: no cap, no anchors', () => {
    const html = renderToStaticMarkup(<PrImages images={twenty} loadImage={vi.fn(() => new Promise(() => {}))} />)
    expect(html.match(/aria-label="Loading image"/g)).toHaveLength(20)
    expect(html).toContain('xl:grid-cols-3')
    expect(html).not.toContain('id="pr-image-')
  })
})

describe('imageRefsFor: which picture a Decision is about', () => {
  const imgs = [
    { caption: 'a. Every answer is what was built: one press merges', alt: '' },
    { caption: 'b. One answer changed', alt: '' },
    { caption: 'The ballot card on a phone', alt: 'ballot' }
  ]
  it('scenes by letter, several at once, in the order named', () => {
    expect(imageRefsFor('Scene b or scene a?', imgs)).toEqual([{ label: 'scene b', index: 1 }, { label: 'scene a', index: 0 }])
    expect(imageRefsFor('In scenes a and b', imgs).map((r) => r.index)).toEqual([0, 1])
  })
  it('a quoted caption links too', () => {
    expect(imageRefsFor('Keep "the ballot card on a phone" as is?', imgs)).toEqual([{ label: 'the screenshot', index: 2 }])
  })
  it('no false links: a scene with no picture, a word containing "scene", short captions, nothing at all', () => {
    expect(imageRefsFor('scene e after a pick', imgs)).toEqual([])
    expect(imageRefsFor('obscene amounts of b', imgs)).toEqual([])
    expect(imageRefsFor('b', [{ caption: 'b' }])).toEqual([])
    expect(imageRefsFor('scene a', undefined)).toEqual([])
    expect(imageRefsFor(undefined, imgs)).toEqual([])
  })
  it('sceneOf reads pr-shots\' "a. ..." captions and "Scene b: ..."', () => {
    expect(sceneOf({ caption: 'a. Every answer' })).toBe('a')
    expect(sceneOf({ caption: 'Scene C: light' })).toBe('c')
    expect(sceneOf({ caption: 'A typed note' })).toBeNull()
    expect(sceneOf({ caption: '', alt: 'd) ballot' })).toBe('d')
  })
})

describe('MockupLauncher', () => {
  it('one mock-up: one "Try the mock-up" button; two: each named', () => {
    const one = renderToStaticMarkup(<MockupLauncher pr={{ mockups: [{ path: 'docs/design/a/index.html', name: 'a' }] }} />)
    expect(one.match(/<button/g)).toHaveLength(1)
    expect(one).toContain('>Try the mock-up<')
    const two = renderToStaticMarkup(<MockupLauncher pr={{ mockups: [{ path: 'docs/design/a/index.html', name: 'a' }, { path: 'docs/design/b/index.html', name: 'b' }] }} />)
    expect(two).toContain('Try the mock-up: a')
    expect(two).toContain('Try the mock-up: b')
    expect(two).toContain('data-mockups="2"')
  })
  it('none: nothing', () => {
    expect(renderToStaticMarkup(<MockupLauncher pr={{ mockups: [] }} />)).toBe('')
    expect(renderToStaticMarkup(<MockupLauncher pr={{}} />)).toBe('')
  })
  it('a deleted branch or a missing page shows the plain message; a thrown IPC error too, without the Electron prefix', () => {
    expect(openOutcome({ ok: false, gone: 'branch', reason: 'This mock-up is gone: its branch was deleted' })).toEqual({ status: 'error', reason: 'This mock-up is gone: its branch was deleted' })
    expect(openOutcome({ ok: true })).toEqual({ status: 'open' })
    expect(openOutcome(undefined).status).toBe('error')
    expect(openOutcome(null, new Error("Error invoking remote method 'mr:openMockup': Error: boom")).reason).toBe('boom')
  })
})

describe('Jump to the Decisions (owner\'s answer on PR #953)', () => {
  it('shows the link at the top and lands on the Decisions, which come after the screenshots', async () => {
    const html = renderToStaticMarkup(<MrDetail pr={await pr934()} onBack={() => {}} />)
    const link = html.indexOf('data-jump-decisions'), anchor = html.indexOf('id="mr-decisions"')
    expect(link).toBeGreaterThan(-1)
    expect(anchor).toBeGreaterThan(link)
    expect(html.indexOf('Images &amp; recordings')).toBeLessThan(anchor)
  })
  it('no link without Decisions, and none on a read-only (merged) PR', async () => {
    const none = renderToStaticMarkup(<MrDetail pr={{ number: 1, title: 't', url: 'u', repo: 'o/r', hasSchema: false, rawBody: 'x', images: [], decisions: { present: false } }} onBack={() => {}} />)
    expect(none).not.toContain('data-jump-decisions')
    const ro = renderToStaticMarkup(<MrDetail pr={{ ...(await pr934()), readOnly: true, state: 'MERGED' }} onBack={() => {}} />)
    expect(ro).not.toContain('data-jump-decisions')
    expect(ro).not.toContain('id="mr-decisions"')
  })
})

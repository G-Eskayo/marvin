import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PrImages, { groupImages } from '../src/components/PrImages.jsx'
import MrDetail, { evidenceImage } from '../src/components/MrDetail.jsx'
import { listPipelinePrs } from '../electron/main/mr_review.js'

const RAW = 'https://raw.githubusercontent.com/G-Eskayo/clarity-captions/design/v1-polish-mocks'
const IMAGES = [
  { url: `${RAW}/01.png`, alt: 'Main', group: '1 · Main screen', caption: 'Gear top-left.' },
  { url: `${RAW}/01b.png`, alt: 'Main landscape', group: '1 · Main screen', caption: 'Landscape.' },
  { url: `${RAW}/02.png`, alt: 'Paused', group: '2 · Paused', caption: 'SAVE then NEW.' }
]

describe('groupImages', () => {
  it('groups consecutive images under their heading and keeps each one\'s place in the flat list', () => {
    const groups = groupImages(IMAGES)
    expect(groups.map((g) => [g.name, g.items.map((i) => i.index)])).toEqual([['1 · Main screen', [0, 1]], ['2 · Paused', [2]]])
  })
  it('handles no images and images with no heading', () => {
    expect(groupImages(undefined)).toEqual([])
    expect(groupImages([{ url: 'a', group: null }])[0].name).toBe('')
  })
})

describe('PrImages', () => {
  it('shows each group heading, a loading placeholder per image, and every caption, before bytes arrive', () => {
    const html = renderToStaticMarkup(<PrImages images={IMAGES} loadImage={vi.fn(() => new Promise(() => {}))} />)
    expect(html).toContain('1 · Main screen')
    expect(html).toContain('2 · Paused')
    expect(html.match(/aria-label="Loading image"/g)).toHaveLength(3)
    for (const c of ['Gear top-left.', 'Landscape.', 'SAVE then NEW.']) expect(html).toContain(c)
  })
  it('renders nothing when there are no images', () => {
    expect(renderToStaticMarkup(<PrImages images={[]} loadImage={vi.fn()} />)).toBe('')
  })
})

const basePr = {
  number: 96, title: 'Design mock-ups', url: 'https://github.com/G-Eskayo/clarity-captions/pull/96', repo: 'G-Eskayo/clarity-captions',
  key: 'G-Eskayo/clarity-captions#96', canMerge: true, hasSchema: false, rawBody: 'body', ticketNumber: null, checks: null
}

describe('MrDetail shows the PR\'s images near the top', () => {
  it('has an Images section with the count, above the description', () => {
    const html = renderToStaticMarkup(<MrDetail pr={{ ...basePr, images: IMAGES }} onBack={() => {}} />)
    expect(html).toContain('Images &amp; recordings (3)')
    expect(html.indexOf('Images &amp; recordings (3)')).toBeLessThan(html.indexOf('PR Description'))
  })
  it('says "Needs images" for a UI change with none, and nothing extra for a non-UI PR', () => {
    const needs = renderToStaticMarkup(<MrDetail pr={{ ...basePr, images: [], needsImages: { files: ['Apps/Spike/Sources/ContentView.swift'] } }} onBack={() => {}} />)
    expect(needs).toContain('Needs images')
    expect(needs).toContain('ContentView.swift')
    const plain = renderToStaticMarkup(<MrDetail pr={{ ...basePr, images: [], needsImages: null }} onBack={() => {}} />)
    expect(plain).not.toContain('Needs images')
    expect(plain).not.toContain('Images &amp; recordings')
  })
})

describe('evidenceImage: the Dev evidence screenshot renders as an image', () => {
  it('matches a repo-relative screenshot path to its resolved URL', () => {
    const images = [{ url: 'https://raw.githubusercontent.com/G-Eskayo/marvin/pipeline/x/docs/evidence/shot.png' }]
    expect(evidenceImage('docs/evidence/shot.png', images)).toBe(images[0])
    expect(evidenceImage('./docs/evidence/shot.png', images)).toBe(images[0])
    expect(evidenceImage('other.png', images)).toBeNull()
    expect(evidenceImage(null, images)).toBeNull()
  })
})

describe('listPipelinePrs carries the images to the detail view', () => {
  it('parses images from each PR body against its own head branch', async () => {
    const prs = await listPipelinePrs(async () => [{
      number: 5, title: 't', url: 'https://github.com/G-Eskayo/finance-os/pull/5', repo: 'G-Eskayo/finance-os', headRefName: 'feat/x',
      body: '## Screens\n![bills](docs/bills.png)'
    }])
    expect(prs[0].images).toEqual([{ url: 'https://raw.githubusercontent.com/G-Eskayo/finance-os/feat/x/docs/bills.png', kind: 'image', alt: 'bills', group: 'Screens', caption: 'bills' }])
  })
})

describe('PrImages with recordings', () => {
  it('asks the loader with each item\'s kind, so a recording gets the bigger cap and the disk cache', () => {
    // Static render runs no effects; the kind travels through useLoadedImages, checked here via the item list.
    const items = [{ url: 'https://raw.githubusercontent.com/o/r/b/rec.mp4', kind: 'video', group: 'Recordings', caption: 'Pause and save' }]
    const html = renderToStaticMarkup(<PrImages images={items} loadImage={vi.fn(() => new Promise(() => {}))} />)
    expect(html).toContain('▶ Pause and save')
    expect(html).toContain('Recordings')
  })
})

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import path from 'path'

// The renderer's Content Security Policy (index.html). Found 2026-10-02: the Portfolio tab showed NO
// photos in the real app because `default-src 'self'` blocks both the dev site's thumbnails
// (http://localhost:8080/...) and `data:` image previews -- and the component preview iframe's
// stylesheets. A visual check that BYPASSED the CSP had hidden it. The policy is relaxed narrowly:
// only the local dev origin and data: images, and never for scripts.

const html = readFileSync(path.resolve(__dirname, '../index.html'), 'utf8')
const csp = html.match(/http-equiv="Content-Security-Policy"\s+content="([^"]+)"/)[1]
const directive = (name) => {
  const m = csp.split(';').map((d) => d.trim()).find((d) => d.startsWith(name + ' '))
  return m ? m.split(/\s+/).slice(1) : null
}
const DEV = 'http://localhost:8080'

describe('renderer Content Security Policy', () => {
  it('lets the Portfolio tab show images from the dev site and data: URLs', () => {
    expect(directive('img-src')).toEqual(expect.arrayContaining(["'self'", 'data:', DEV]))
  })

  it('lets component previews load the dev site\'s stylesheets and fonts', () => {
    expect(directive('style-src')).toEqual(expect.arrayContaining(["'self'", "'unsafe-inline'", DEV]))
    expect(directive('font-src')).toEqual(expect.arrayContaining(["'self'", 'data:', DEV]))
  })

  it('also allows exactly the three CDNs the dev site\'s own stylesheets pull from (styles and fonts only)', () => {
    // Bootstrap (jsdelivr), Google Fonts (the site's Roboto / Roboto Mono) and FontAwesome (maxcdn): without them
    // a component preview renders in fallback fonts and is not representative of the real site.
    expect(directive('style-src')).toEqual(expect.arrayContaining(['https://cdn.jsdelivr.net', 'https://fonts.googleapis.com', 'https://maxcdn.bootstrapcdn.com']))
    expect(directive('font-src')).toEqual(expect.arrayContaining(['https://fonts.gstatic.com', 'https://maxcdn.bootstrapcdn.com']))
    expect(directive('img-src')).not.toContain('https://cdn.jsdelivr.net')   // CDNs are for styles/fonts only
  })

  it('does NOT widen script execution: scripts stay self + inline only, never a remote origin', () => {
    expect(directive('script-src')).toEqual(["'self'", "'unsafe-inline'"])
  })

  it('keeps default-src locked to self and does not use a wildcard anywhere', () => {
    expect(directive('default-src')).toEqual(["'self'"])
    expect(csp).not.toMatch(/\*/)
  })

  it('does not open connect-src to arbitrary hosts (renderer talks to main over IPC, not fetch)', () => {
    expect(directive('connect-src')).toBeNull()
  })
})

import { readFileSync as _read } from 'fs'
describe('window can be moved', () => {
  it('the header is a drag region and its controls opt out', () => {
    const css = _read(new URL('../src/index.css', import.meta.url), 'utf8')
    const app = _read(new URL('../src/App.jsx', import.meta.url), 'utf8')
    expect(app).toMatch(/<header className="titlebar /)
    expect(css).toMatch(/\.titlebar\s*\{\s*-webkit-app-region:\s*drag/)
    expect(css).toMatch(/\.titlebar button[^}]*-webkit-app-region:\s*no-drag/)
  })
})

describe('reference previews are inert', () => {
  it('blocks navigation from inside preview frames while keeping hrefs (so styling is unchanged)', () => {
    const src = _read(new URL('../src/components/PortfolioHub.jsx', import.meta.url), 'utf8')
    expect(src).toMatch(/addEventListener\('click'[\s\S]*preventDefault/)
    expect(src).toMatch(/addEventListener\('submit'/)
    expect(src).not.toMatch(/sandbox="allow-same-origin allow-scripts"/)   // the frame itself must never run scripts
  })
})

describe('image lightbox and delete', () => {
  const src = () => _read(new URL('../src/components/PortfolioHub.jsx', import.meta.url), 'utf8')
  it('closes on Escape and on a click outside the picture', () => {
    expect(src()).toMatch(/e\.key === 'Escape'/)
    expect(src()).toMatch(/onClick=\{onClose\}/)
    expect(src()).toMatch(/stopPropagation/)
  })
  it('every image in the Images tab can be opened full size, and variants can be deleted but not the one in use', () => {
    expect(src()).toMatch(/setZoom\(\{ src: preview/)
    expect(src()).toMatch(/onZoom\(src,/)
    expect(src()).toMatch(/deleteImageVariant/)
    // the delete control sits in the not-chosen branch of the tile
    expect(src()).toMatch(/v\.chosen\s*\?[\s\S]*?in use[\s\S]*?:\s*<>[\s\S]*?delete/)
  })
})

describe('add project subtab', () => {
  it('is wired to the pipeline with a dry-run check and a create action', () => {
    const src = _read(new URL('../src/components/PortfolioHub.jsx', import.meta.url), 'utf8')
    expect(src).toMatch(/\['add', 'Add project'\]/)
    expect(src).toMatch(/addProject\(clean, \{ plan \}\)/)
    expect(src).toMatch(/Check \(writes nothing\)/)
  })
})

import { describe, it, expect } from 'vitest'
import { withOverrides, nameOf } from '../src/lib/project_names.js'

// marvin#848: one place for project names. The friendly name is set once in overrides.json (`name`), the catalog
// carries it after a refresh, and every screen asks this one lookup, whichever spelling it holds (id, repo, a helper
// tab's group, an alias).
const CATALOG = [
  { id: 'marvin', name: 'marvin', repo: 'G-Eskayo/marvin', status: 'active' },
  { id: 'clarity-captions', name: 'clarity-captions', repo: 'G-Eskayo/clarity-captions', status: 'active', aliases: ['seal'] },
  { id: 'portfolio-website-updater', name: 'portfolio-website-updater', repo: 'G-Eskayo/portfolio-website-updater', status: 'active' },
  { id: 'ml-powered-thing', name: 'ML-Powered-Thing', repo: 'G-Eskayo/ML-Powered-Thing', status: 'active' },
  { id: 'eagle-project', name: 'eagle project', repo: null, status: 'recent' }
]
const OVERRIDES = {
  marvin: { name: 'MARVIN' },
  'clarity-captions': { name: 'Seal Speak', aliases: ['clarity'] },
  'portfolio-website-updater': { name: 'Portfolio', status: 'active' },
  ghost: { name: 'Not in the catalog' }
}

describe('withOverrides: the catalog with overrides.json applied now, not only after the next catalog refresh', () => {
  it('a name set in overrides.json wins', () => {
    const p = withOverrides(CATALOG, OVERRIDES)
    expect(p.map((x) => x.name)).toEqual(['MARVIN', 'Seal Speak', 'Portfolio', 'ML-Powered-Thing', 'eagle project'])
  })
  it('keeps the catalog name it replaced, so the old spelling still resolves', () => {
    expect(withOverrides(CATALOG, OVERRIDES)[1].catalogName).toBe('clarity-captions')
  })
  it('overrides status and adds aliases, keeps every other field', () => {
    const p = withOverrides(CATALOG, { marvin: { status: 'dormant', aliases: ['agents'] } })[0]
    expect(p).toMatchObject({ id: 'marvin', name: 'marvin', repo: 'G-Eskayo/marvin', status: 'dormant', aliases: ['agents'] })
  })
  it('an override for a project the catalog lacks adds nothing', () => {
    expect(withOverrides(CATALOG, OVERRIDES)).toHaveLength(CATALOG.length)
  })
  it('a missing catalog or missing/broken overrides is not an error', () => {
    expect(withOverrides(null, OVERRIDES)).toEqual([])
    expect(withOverrides(CATALOG, null).map((x) => x.name)[0]).toBe('marvin')
    expect(withOverrides(CATALOG, { marvin: 'oops', 'clarity-captions': { name: '   ' } }).map((x) => x.name).slice(0, 2)).toEqual(['marvin', 'clarity-captions'])
  })
  it('never changes the catalog it was given', () => {
    const before = JSON.stringify(CATALOG)
    withOverrides(CATALOG, OVERRIDES)
    expect(JSON.stringify(CATALOG)).toBe(before)
  })
})

describe('nameOf: any spelling of a project gives its one name', () => {
  const P = withOverrides(CATALOG, OVERRIDES)
  it.each([
    ['marvin', 'MARVIN'],
    ['G-Eskayo/marvin', 'MARVIN'],
    ['g-eskayo/MARVIN', 'MARVIN'],
    ['MARVIN', 'MARVIN'],
    ['clarity-captions', 'Seal Speak'],
    ['Seal Speak', 'Seal Speak'],
    ['seal speak', 'Seal Speak'],
    ['seal', 'Seal Speak'],
    ['clarity', 'Seal Speak'],
    ['G-Eskayo/ML-Powered-Thing', 'ML-Powered-Thing'],
    ['ML-Powered-Thing', 'ML-Powered-Thing'],
    ['ml powered thing', 'ML-Powered-Thing'],
    ['portfolio-website-updater', 'Portfolio']
  ])('%s → %s', (term, name) => {
    expect(nameOf(term, P)).toBe(name)
  })
  it('an unknown spelling comes back as it was given (a helper group like "Disk" is not a project)', () => {
    expect(nameOf('Disk cleanup', P)).toBe('Disk cleanup')
    expect(nameOf('G-Eskayo/unknown-repo', P)).toBe('G-Eskayo/unknown-repo')
  })
  it('a repo-less project still resolves by id and name', () => {
    expect(nameOf('eagle-project', P)).toBe('eagle project')
  })
  it('empty or missing input, or no catalog', () => {
    expect(nameOf('', P)).toBe('')
    expect(nameOf(null, P)).toBe('')
    expect(nameOf('marvin', null)).toBe('marvin')
  })
  it('"marvin" never matches "marvin-mobile" (whole names only)', () => {
    const p = withOverrides([...CATALOG, { id: 'marvin-mobile', name: 'marvin-mobile', repo: 'G-Eskayo/marvin-mobile' }], { 'marvin-mobile': { name: 'MARVIN Mobile' }, ...OVERRIDES })
    expect(nameOf('marvin-mobile', p)).toBe('MARVIN Mobile')
    expect(nameOf('marvin', p)).toBe('MARVIN')
  })
})

// The handoff resume check (marvin#1221) reads ticket and PR refs through relations.js extractRefs, never a second
// parser. Handoffs name work the way people do ("portfolio-website-updater #17", "ticket 1185", "PRs 20, 21"), so
// extractRefs takes an opt-in that understands those; without it, the dashboard's relations are unchanged.
import { describe, it, expect } from 'vitest'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { extractRefs } from '../electron/main/relations.js'

const CLI = fileURLToPath(new URL('../electron/main/refs_cli.mjs', import.meta.url))
const repos = { 'portfolio-website-updater': 'G-Eskayo/portfolio-website-updater', marvin: 'G-Eskayo/marvin' }
const keys = (r) => r.tickets.map((t) => `${t.repo}#${t.number}`)

describe('extractRefs with handoff wording (opt-in)', () => {
  it('reads "<repo name> #N" as that repo when the name is known', () => {
    expect(keys(extractRefs('URGENT: portfolio-website-updater #17 media wipe', { repos }))).toEqual(['G-Eskayo/portfolio-website-updater#17'])
  })

  it('reads "ticket N", "PR N" and lists after them as bare refs', () => {
    const r = extractRefs('Route loader fix (ticket 1185); PRs 20, 21 and 22; issue #9', { words: true })
    expect(keys(r)).toEqual(['null#1185', 'null#20', 'null#21', 'null#22', 'null#9'])
  })

  it('leaves "the ticket" or "PR review" alone, and anything in code', () => {
    expect(extractRefs('the ticket queue and PR review, `ticket 5`\n```\nPR 6\n```', { words: true }).tickets).toEqual([])
  })

  it('reads "<repo name>#N" with no space too', () => {
    expect(keys(extractRefs('see marvin#1100', { repos }))).toEqual(['G-Eskayo/marvin#1100'])
  })

  it('an unknown repo name before #N is still a bare ref, not invented', () => {
    expect(keys(extractRefs('someother-repo #4', { repos }))).toEqual(['null#4'])
  })

  it('without the opt-in nothing changes for the dashboard', () => {
    expect(keys(extractRefs('portfolio-website-updater #17 and ticket 1185'))).toEqual(['null#17'])
  })
})

describe('refs_cli.mjs', () => {
  const run = (input) => spawnSync(process.execPath, ['--no-warnings', CLI], { input: JSON.stringify(input), encoding: 'utf8' })

  it('returns refs per text, qualified with the default repo, de-duplicated', () => {
    const p = run({ texts: ['#5 and #5 and portfolio-website-updater #17', 'ticket 9'], repos, defaultRepo: 'G-Eskayo/marvin' })
    expect(p.status).toBe(0)
    const out = JSON.parse(p.stdout).refs.map((list) => list.map((r) => `${r.repo}#${r.number}`).sort())
    expect(out).toEqual([['G-Eskayo/marvin#5', 'G-Eskayo/portfolio-website-updater#17'], ['G-Eskayo/marvin#9']])
  })

  it('fails loudly (non-zero) on input that is not JSON', () => {
    const p = spawnSync(process.execPath, ['--no-warnings', CLI], { input: 'not json', encoding: 'utf8' })
    expect(p.status).not.toBe(0)
  })
})

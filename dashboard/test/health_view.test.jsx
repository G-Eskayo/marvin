import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { verdictLine } from '../src/lib/health_view.js'
import { OverallBadge } from '../src/components/HealthDashboard.jsx'

describe('verdictLine: verdict banner color and text from overall + age', () => {
  describe('fresh and healthy', () => {
    it('shows green "healthy · X min ago" when overall is green and fresh', () => {
      const result = verdictLine('green', { ageS: 300, stale: false, toleranceS: 1200 })
      expect(result).toEqual({
        severity: 'green',
        stale: false,
        text: expect.stringMatching(/healthy.*5 min ago/i)
      })
    })
    it('shows the age in relative time: minutes, hours, days', () => {
      const cases = [
        { ageS: 0, text: /just now/i },
        { ageS: 30, text: /just now/i },
        { ageS: 300, text: /5 min ago/i },
        { ageS: 3600, text: /1 h ago/i },
        { ageS: 7200, text: /2 h ago/i },
        { ageS: 86400, text: /24 h ago/i },
        { ageS: 172800, text: /2 days ago/i }
      ]
      for (const c of cases) {
        const result = verdictLine('green', { ageS: c.ageS, stale: false, toleranceS: 1200 })
        expect(result.text, `ageS ${c.ageS}`).toMatch(c.text)
      }
    })
  })

  describe('stale overrides every severity', () => {
    it('stale green shows amber "verdict is old · sweep hasn\'t run" despite overall: green', () => {
      const result = verdictLine('green', { ageS: 1300, stale: true, toleranceS: 1200 })
      expect(result.severity).toBe('yellow')
      expect(result.stale).toBe(true)
      expect(result.text).toMatch(/old.*sweep hasn't run/i)
    })
    it('stale red shows amber, not red, with the same old/sweep text', () => {
      const result = verdictLine('red', { ageS: 1300, stale: true, toleranceS: 1200 })
      expect(result.severity).toBe('yellow')
      expect(result.stale).toBe(true)
      expect(result.text).toMatch(/old.*sweep hasn't run/i)
    })
    it('stale yellow shows amber with the same wording', () => {
      const result = verdictLine('yellow', { ageS: 1300, stale: true, toleranceS: 1200 })
      expect(result.severity).toBe('yellow')
      expect(result.stale).toBe(true)
      expect(result.text).toMatch(/old.*sweep hasn't run/i)
    })
  })

  describe('boundary at tolerance', () => {
    it('exactly at tolerance is not stale', () => {
      const result = verdictLine('green', { ageS: 1200, stale: false, toleranceS: 1200 })
      expect(result.stale).toBe(false)
      expect(result.text).not.toMatch(/old.*sweep/i)
    })
    it('one second past tolerance is stale', () => {
      const result = verdictLine('green', { ageS: 1201, stale: true, toleranceS: 1200 })
      expect(result.stale).toBe(true)
      expect(result.text).toMatch(/old.*sweep/i)
    })
  })

  describe('missing or malformed copy', () => {
    it('undefined copy is treated as unknown age, downgrades to yellow', () => {
      const result = verdictLine('green', undefined)
      expect(result.severity).toBe('yellow')
      expect(result.stale).toBe(false)
      expect(result.text).toMatch(/age unknown/i)
    })
    it('null copy is treated as unknown age, downgrades to yellow', () => {
      const result = verdictLine('green', null)
      expect(result.severity).toBe('yellow')
      expect(result.stale).toBe(false)
      expect(result.text).toMatch(/age unknown/i)
    })
    it('copy with null ageS is treated as unknown age', () => {
      const result = verdictLine('green', { ageS: null, stale: false, toleranceS: 1200 })
      expect(result.severity).toBe('green')
      expect(result.text).toMatch(/age unknown/i)
    })
    it('partial snapshot (missing toleranceS) still works', () => {
      const result = verdictLine('green', { ageS: 300 })
      expect(result.severity).toBe('green')
      expect(result.text).toMatch(/5 min ago/i)
    })
    it('copy with extra unknown fields is ignored', () => {
      const result = verdictLine('green', { ageS: 300, stale: false, toleranceS: 1200, producerUnreachable: true, from: 'mini' })
      expect(result.severity).toBe('green')
      expect(result.text).toMatch(/5 min ago/i)
    })
  })

  describe('bad/malformed input', () => {
    it('unexpected overall values normalize to yellow', () => {
      for (const bad of [undefined, null, 123, 'purple', 'GREEN', '']) {
        const result = verdictLine(bad, { ageS: 300, stale: false, toleranceS: 1200 })
        expect(result.severity).toBe('yellow')
      }
    })
    it('negative ageS is clamped to 0', () => {
      const result = verdictLine('green', { ageS: -100, stale: false, toleranceS: 1200 })
      expect(result.text).toMatch(/just now/i)
    })
    it('NaN ageS is treated as unknown age', () => {
      const result = verdictLine('green', { ageS: NaN, stale: false, toleranceS: 1200 })
      expect(result.text).toMatch(/age unknown/i)
    })
    it('Infinity ageS is treated as very old', () => {
      const result = verdictLine('green', { ageS: Infinity, stale: true, toleranceS: 1200 })
      expect(result.text).toMatch(/very old|age unknown/i)
    })
  })

  describe('huge input', () => {
    it('very large ageS renders as days old with stale wording', () => {
      const result = verdictLine('green', { ageS: 20_000_000, stale: true, toleranceS: 1200 })
      expect(result.text).toMatch(/days? old.*sweep hasn't run/i)
    })
  })

  describe('a person refreshing', () => {
    it('clicking Refresh now while stale clears the amber once fresh', () => {
      const staleResult = verdictLine('green', { ageS: 1300, stale: true, toleranceS: 1200 })
      expect(staleResult.stale).toBe(true)

      const freshResult = verdictLine('green', { ageS: 0, stale: false, toleranceS: 1200 })
      expect(freshResult.stale).toBe(false)
      expect(freshResult.text).not.toMatch(/old.*sweep/i)
    })
  })
})

describe('OverallBadge: rendered verdict line with Refresh button', () => {
  it('stale copy shows amber text with "old" and "sweep" and always has Refresh now button', () => {
    const html = renderToStaticMarkup(
      <OverallBadge
        overall="green"
        copy={{ ageS: 1300, stale: true, toleranceS: 1200 }}
        generatedAt={new Date(Date.now() - 1300 * 1000).toISOString()}
        refreshing={false}
        onRefresh={() => {}}
      />
    )
    expect(html).toContain('Refresh now')
    expect(html).toMatch(/old.*sweep/i)
  })

  it('fresh green copy shows "healthy · X ago" with Refresh now button', () => {
    const html = renderToStaticMarkup(
      <OverallBadge
        overall="green"
        copy={{ ageS: 300, stale: false, toleranceS: 1200 }}
        generatedAt={new Date(Date.now() - 300 * 1000).toISOString()}
        refreshing={false}
        onRefresh={() => {}}
      />
    )
    expect(html).toContain('Refresh now')
    expect(html).toMatch(/healthy.*min ago/i)
  })

  it('Refresh now button is always present regardless of state', () => {
    for (const state of [
      { overall: 'green', copy: { ageS: 300, stale: false, toleranceS: 1200 } },
      { overall: 'green', copy: { ageS: 1300, stale: true, toleranceS: 1200 } },
      { overall: 'red', copy: { ageS: 300, stale: false, toleranceS: 1200 } }
    ]) {
      const html = renderToStaticMarkup(
        <OverallBadge
          overall={state.overall}
          copy={state.copy}
          generatedAt={new Date().toISOString()}
          refreshing={false}
          onRefresh={() => {}}
        />
      )
      expect(html, `state: ${JSON.stringify(state)}`).toContain('Refresh now')
    }
  })
})

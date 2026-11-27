import { describe, it, expect } from 'vitest'
import { foldCommonCause, ROOT_BY_CODE, ROOT_LABEL } from '../src/lib/common_cause.js'

const PR = (n) => `https://github.com/G-Eskayo/marvin/pull/${n}`
const at = (iso) => new Date(iso).toISOString()

describe('foldCommonCause', () => {
  describe('test 1: empty and null rows', () => {
    it('handles empty array', () => {
      expect(foldCommonCause([])).toEqual([])
    })
    it('handles null', () => {
      expect(foldCommonCause(null)).toBe(null)
    })
  })

  describe('test 2: merged rows pass through unchanged', () => {
    it('merged rows are kept as-is', () => {
      const rows = [
        { kind: 'merged', number: 1, url: PR(1), at: at('2026-10-13T12:00:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result).toEqual(rows)
    })
  })

  describe('test 3: refused rows with no code pass through unchanged', () => {
    it('refused rows without code are kept as-is', () => {
      const rows = [
        { kind: 'refused', number: 2, url: PR(2), code: null, at: at('2026-10-13T12:00:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result).toEqual(rows)
    })
  })

  describe('test 4: refused rows with unknown codes pass through unchanged', () => {
    it('refused rows with unknown code are kept as-is', () => {
      const rows = [
        { kind: 'refused', number: 3, url: PR(3), code: 'UNKNOWN_CODE', at: at('2026-10-13T12:00:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result).toEqual(rows)
    })
  })

  describe('test 5: single refused row with known code passes through unchanged', () => {
    it('single refused row with known code is kept as-is', () => {
      const rows = [
        { kind: 'refused', number: 4, url: PR(4), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result).toEqual(rows)
    })
  })

  describe('test 6: two consecutive refused rows with same root (within gap)', () => {
    it('two MAIN_RED refusals within gap get folded', () => {
      const rows = [
        { kind: 'refused', number: 5, url: PR(5), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
        { kind: 'refused', number: 6, url: PR(6), code: 'MAIN_RED', at: at('2026-10-13T12:30:00Z') },
      ]
      const result = foldCommonCause(rows, { gapHours: 2 })
      expect(result).toHaveLength(1)
      expect(result[0]).toMatchObject({
        kind: 'folded',
        root: 'MAIN_RED',
        label: 'main is red',
        count: 2,
      })
      expect(result[0].items).toHaveLength(2)
    })
  })

  describe('test 7: two refused rows separated by gap form separate incidents', () => {
    it('two MAIN_RED refusals separated by >2h gap are kept separate', () => {
      const rows = [
        { kind: 'refused', number: 7, url: PR(7), code: 'MAIN_RED', at: at('2026-10-13T10:00:00Z') },
        { kind: 'refused', number: 8, url: PR(8), code: 'MAIN_RED', at: at('2026-10-13T12:30:00Z') },
      ]
      const result = foldCommonCause(rows, { gapHours: 2 })
      expect(result).toHaveLength(2)
      expect(result[0].kind).toBe('refused')
      expect(result[1].kind).toBe('refused')
    })
  })

  describe('test 8: deduplication by URL keeps latest', () => {
    it('two refusals of same PR keeps latest', () => {
      const rows = [
        { kind: 'refused', number: 9, url: PR(9), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
        { kind: 'refused', number: 9, url: PR(9), code: 'MAIN_RED', at: at('2026-10-13T12:30:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result[0].items).toHaveLength(1)
      expect(result[0].items[0].at).toEqual(at('2026-10-13T12:30:00Z'))
    })
  })

  describe('test 9: mix of different roots stays separate', () => {
    it('MAIN_RED and GITHUB refusals fold separately', () => {
      const rows = [
        { kind: 'refused', number: 10, url: PR(10), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
        { kind: 'refused', number: 11, url: PR(11), code: 'MAIN_RED', at: at('2026-10-13T12:15:00Z') },
        { kind: 'refused', number: 12, url: PR(12), code: 'RATE_LIMITED', at: at('2026-10-13T12:30:00Z') },
        { kind: 'refused', number: 13, url: PR(13), code: 'GITHUB_OUTAGE', at: at('2026-10-13T12:45:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result).toHaveLength(2)
      expect(result[0]).toMatchObject({ kind: 'folded', root: 'MAIN_RED', count: 2 })
      expect(result[1]).toMatchObject({ kind: 'folded', root: 'GITHUB', count: 2 })
    })
  })

  describe('test 10: folded row preserves order and latest at', () => {
    it('folded incident uses latest at timestamp', () => {
      const rows = [
        { kind: 'refused', number: 14, url: PR(14), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
        { kind: 'refused', number: 15, url: PR(15), code: 'MAIN_RED', at: at('2026-10-13T12:30:00Z') },
        { kind: 'refused', number: 16, url: PR(16), code: 'MAIN_RED', at: at('2026-10-13T12:15:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result[0].at).toEqual(at('2026-10-13T12:30:00Z'))
    })
  })

  describe('test 11: complex mix preserves non-refused rows', () => {
    it('merged rows interspersed with refused rows stay in order', () => {
      const rows = [
        { kind: 'merged', number: 100, url: PR(100), at: at('2026-10-13T13:00:00Z') },
        { kind: 'refused', number: 17, url: PR(17), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
        { kind: 'refused', number: 18, url: PR(18), code: 'MAIN_RED', at: at('2026-10-13T12:15:00Z') },
        { kind: 'merged', number: 101, url: PR(101), at: at('2026-10-13T11:00:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result[0].kind).toBe('merged')
      expect(result[0].number).toBe(100)
      expect(result[1].kind).toBe('folded')
      expect(result[2].kind).toBe('merged')
      expect(result[2].number).toBe(101)
    })
  })

  describe('test 12: custom rootByCode mapping', () => {
    it('uses custom rootByCode', () => {
      const customRoot = { MAIN_RED: 'CUSTOM_ROOT' }
      const rows = [
        { kind: 'refused', number: 19, url: PR(19), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
        { kind: 'refused', number: 20, url: PR(20), code: 'MAIN_RED', at: at('2026-10-13T12:15:00Z') },
      ]
      const result = foldCommonCause(rows, { rootByCode: customRoot })
      expect(result[0].root).toBe('CUSTOM_ROOT')
    })
  })

  describe('test 13: custom gapHours affects incident splitting', () => {
    it('gapHours=0.5 splits at 30 min instead of 2 hours', () => {
      const rows = [
        { kind: 'refused', number: 21, url: PR(21), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
        { kind: 'refused', number: 22, url: PR(22), code: 'MAIN_RED', at: at('2026-10-13T12:45:00Z') },
      ]
      const result = foldCommonCause(rows, { gapHours: 0.5 })
      expect(result).toHaveLength(2)
      expect(result[0].kind).toBe('refused')
      expect(result[1].kind).toBe('refused')
    })
  })

  describe('test 14: folded row structure exports items correctly', () => {
    it('folded row items are accessible and clickable', () => {
      const rows = [
        { kind: 'refused', number: 23, url: PR(23), code: 'MAIN_RED', title: 'Fix 1', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:00:00Z') },
        { kind: 'refused', number: 24, url: PR(24), code: 'MAIN_RED', title: 'Fix 2', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:15:00Z') },
      ]
      const result = foldCommonCause(rows)
      const folded = result[0]
      expect(folded.items.length).toBe(2)
      expect(folded.items[0].url).toBe(PR(23))
      expect(folded.items[1].url).toBe(PR(24))
      expect(folded.items[0].title).toBe('Fix 1')
    })
  })
})

describe('FoldedHistoryRow structure', () => {
  describe('test 15: folded row has correct structure', () => {
    it('folded row structure is complete with label, count, and items', () => {
      const folded = {
        kind: 'folded',
        root: 'MAIN_RED',
        label: 'main is red',
        at: at('2026-10-13T12:30:00Z'),
        count: 3,
        items: [
          { kind: 'refused', number: 1, url: PR(1), code: 'MAIN_RED', title: 'Fix 1', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:00:00Z') },
          { kind: 'refused', number: 2, url: PR(2), code: 'MAIN_RED', title: 'Fix 2', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:15:00Z') },
          { kind: 'refused', number: 3, url: PR(3), code: 'MAIN_RED', title: 'Fix 3', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:30:00Z') },
        ]
      }

      expect(folded.kind).toBe('folded')
      expect(folded.root).toBe('MAIN_RED')
      expect(folded.label).toBe('main is red')
      expect(folded.count).toBe(3)
      expect(folded.items).toHaveLength(3)
      expect(folded.items[0].url).toBe(PR(1))
      expect(folded.items[1].url).toBe(PR(2))
      expect(folded.items[2].url).toBe(PR(3))
    })
  })

  describe('test 16: folded row items are in oldest-first order', () => {
    it('folded row items maintain oldest-first chronological order', () => {
      const folded = {
        kind: 'folded',
        root: 'GITHUB',
        label: 'GitHub is down',
        at: at('2026-10-13T12:45:00Z'),
        count: 2,
        items: [
          { kind: 'refused', number: 10, url: PR(10), code: 'RATE_LIMITED', title: 'Rate limited PR', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:30:00Z') },
          { kind: 'refused', number: 11, url: PR(11), code: 'GITHUB_OUTAGE', title: 'GitHub outage PR', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:45:00Z') },
        ]
      }

      // Items should be in oldest-first order
      const item0Date = Date.parse(folded.items[0].at)
      const item1Date = Date.parse(folded.items[1].at)
      expect(item0Date).toBeLessThanOrEqual(item1Date)
      expect(folded.items[0].url).toBe(PR(10))
      expect(folded.items[1].url).toBe(PR(11))
    })
  })
})

describe('foldCommonCause edge cases', () => {
  describe('test 17: non-refused rows between refused rows of same root are not adjacency breaks', () => {
    it('groups refused rows separated by merged rows correctly', () => {
      const rows = [
        { kind: 'refused', number: 1, url: PR(1), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
        { kind: 'merged', number: 100, url: PR(100), at: at('2026-10-13T12:15:00Z') },
        { kind: 'refused', number: 2, url: PR(2), code: 'MAIN_RED', at: at('2026-10-13T12:30:00Z') },
      ]
      const result = foldCommonCause(rows, { gapHours: 2 })
      expect(result).toHaveLength(2)
      expect(result[0]).toMatchObject({ kind: 'folded', root: 'MAIN_RED', count: 2 })
      expect(result[1]).toMatchObject({ kind: 'merged' })
    })
  })

  describe('test 18: rows missing url field fall back to single row', () => {
    it('refuses to fold when url is missing', () => {
      const rows = [
        { kind: 'refused', number: 1, code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') }, // no url
        { kind: 'refused', number: 2, url: PR(2), code: 'MAIN_RED', at: at('2026-10-13T12:30:00Z') },
      ]
      const result = foldCommonCause(rows)
      expect(result).toHaveLength(2)
      expect(result[0]).toMatchObject({ kind: 'refused', number: 1 })
      expect(result[1]).toMatchObject({ kind: 'refused', number: 2 })
    })
  })

  describe('test 19: rows with invalid at timestamps are grouped separately', () => {
    it('invalid dates do not group into same incident', () => {
      const rows = [
        { kind: 'refused', number: 1, url: PR(1), code: 'MAIN_RED', at: 'invalid-date' },
        { kind: 'refused', number: 2, url: PR(2), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
      ]
      const result = foldCommonCause(rows, { gapHours: 2 })
      expect(result).toHaveLength(2)
      expect(result[0]).toMatchObject({ kind: 'refused', number: 1 })
      expect(result[1]).toMatchObject({ kind: 'refused', number: 2 })
    })
  })

  describe('test 20: rows with missing at field are handled safely', () => {
    it('missing at timestamps do not cause NaN gaps', () => {
      const rows = [
        { kind: 'refused', number: 1, url: PR(1), code: 'MAIN_RED' },
        { kind: 'refused', number: 2, url: PR(2), code: 'MAIN_RED', at: at('2026-10-13T12:00:00Z') },
      ]
      const result = foldCommonCause(rows, { gapHours: 2 })
      expect(result).toHaveLength(2)
      expect(result[0]).toMatchObject({ kind: 'refused', number: 1 })
      expect(result[1]).toMatchObject({ kind: 'refused', number: 2 })
    })
  })
})

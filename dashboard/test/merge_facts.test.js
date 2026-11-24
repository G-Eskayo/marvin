import { describe, it, expect, vi, beforeEach } from 'vitest'
import os from 'os'

vi.mock('fs', async () => {
  const actual = await vi.importActual('fs')
  return {
    ...actual,
    readFileSync: vi.fn()
  }
})

import { readFileSync } from 'fs'
import { readRepairFailures } from '../webhook-server/merge_facts.js'

describe('readRepairFailures', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns an object mapping repo#n to {sha, files}', () => {
    const json = {
      'G-Eskayo/marvin#972': { failed_sha: 'sha972', files: ['src/app.js', 'src/state.js'] },
      'G-Eskayo/clarity-captions#5': { failed_sha: 'sha5', files: ['ui.py'] }
    }
    readFileSync.mockReturnValue(JSON.stringify(json))
    const result = readRepairFailures()
    expect(result['G-Eskayo/marvin#972']).toEqual({ sha: 'sha972', files: ['src/app.js', 'src/state.js'] })
    expect(result['G-Eskayo/clarity-captions#5']).toEqual({ sha: 'sha5', files: ['ui.py'] })
  })

  it('defaults files to [] when not present', () => {
    const json = {
      'G-Eskayo/marvin#1': { failed_sha: 'abc123' }
    }
    readFileSync.mockReturnValue(JSON.stringify(json))
    const result = readRepairFailures()
    expect(result['G-Eskayo/marvin#1']).toEqual({ sha: 'abc123', files: [] })
  })

  it('skips entries without failed_sha', () => {
    const json = {
      'G-Eskayo/marvin#1': { some_other_field: 'value' },
      'G-Eskayo/marvin#2': { failed_sha: 'sha2', files: [] }
    }
    readFileSync.mockReturnValue(JSON.stringify(json))
    const result = readRepairFailures()
    expect(result['G-Eskayo/marvin#1']).toBeUndefined()
    expect(result['G-Eskayo/marvin#2']).toEqual({ sha: 'sha2', files: [] })
  })

  it('handles malformed JSON gracefully', () => {
    readFileSync.mockReturnValue('not json')
    const result = readRepairFailures()
    expect(result).toEqual({})
  })

  it('handles non-object data gracefully', () => {
    readFileSync.mockReturnValue(JSON.stringify('string'))
    const result = readRepairFailures()
    expect(result).toEqual({})
  })
})

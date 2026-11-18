import { describe, it, expect, vi } from 'vitest'
import { parseRunAndJobId, classifyFailure, fetchAnnotations } from '../webhook-server/check_annotations.js'

describe('parseRunAndJobId', () => {
  it('extracts runId and jobId from a valid GitHub actions URL', () => {
    const result = parseRunAndJobId('https://github.com/G-Eskayo/marvin/actions/runs/123/job/456')
    expect(result).toEqual({ runId: '123', jobId: '456' })
  })

  it('handles different repos correctly', () => {
    const result = parseRunAndJobId('https://github.com/owner/repo/actions/runs/999/job/888')
    expect(result).toEqual({ runId: '999', jobId: '888' })
  })

  it('returns null for a URL without /job/', () => {
    expect(parseRunAndJobId('https://github.com/G-Eskayo/marvin/actions/runs/123')).toBe(null)
  })

  it('returns null for null or empty input', () => {
    expect(parseRunAndJobId(null)).toBe(null)
    expect(parseRunAndJobId('')).toBe(null)
    expect(parseRunAndJobId(undefined)).toBe(null)
  })

  it('returns null for a malformed URL', () => {
    expect(parseRunAndJobId('not a url')).toBe(null)
    expect(parseRunAndJobId('https://example.com/actions/runs/123/job/456')).toBe(null)
  })
})

describe('classifyFailure', () => {
  it('returns "no-runner" when annotations array is empty (no failures logged)', () => {
    expect(classifyFailure([])).toBe('no-runner')
  })

  it('returns "no-runner" when every annotation matches no-runner wording', () => {
    const annotations = [
      { title: 'The action is not available from GitHub' },
      { title: 'The job could not be acquired by the runner' }
    ]
    expect(classifyFailure(annotations)).toBe('no-runner')
  })

  it('returns "failure" when mixed annotations include real failing-test wording', () => {
    const annotations = [
      { title: 'The job could not be acquired by the runner' },
      { title: 'AssertionError: expected undefined to be true' }
    ]
    expect(classifyFailure(annotations)).toBe('failure')
  })

  it('returns "failure" for an annotation that is neither no-runner nor recognizable failure (e.g. person cancelled it)', () => {
    const annotations = [
      { title: 'The job was cancelled by the user' }
    ]
    expect(classifyFailure(annotations)).toBe('failure')
  })

  it('returns "failure" for a single non-no-runner annotation', () => {
    const annotations = [
      { title: 'Some other error message' }
    ]
    expect(classifyFailure(annotations)).toBe('failure')
  })

  it('returns "unknown" when annotations is null (failed to fetch)', () => {
    expect(classifyFailure(null)).toBe('unknown')
  })

  it('returns "failure" when annotations is undefined (unexpected)', () => {
    expect(classifyFailure(undefined)).toBe('failure')
  })
})

describe('fetchAnnotations', () => {
  it('calls gh api with correct repo and jobId', async () => {
    const gh = vi.fn().mockResolvedValue('[]')
    await fetchAnnotations('owner/repo', '456', gh)
    expect(gh).toHaveBeenCalledWith(['api', 'repos/owner/repo/check-runs/456/annotations', '--paginate'])
  })

  it('returns parsed JSON array when successful', async () => {
    const annotations = [{ title: 'test annotation' }]
    const gh = vi.fn().mockResolvedValue(JSON.stringify(annotations))
    const result = await fetchAnnotations('owner/repo', '456', gh)
    expect(result).toEqual(annotations)
  })

  it('returns null when gh throws (404 or other error)', async () => {
    const gh = vi.fn().mockRejectedValue(new Error('404 Not Found'))
    const result = await fetchAnnotations('owner/repo', '456', gh)
    expect(result).toBe(null)
  })

  it('returns empty array when response is not valid JSON', async () => {
    const gh = vi.fn().mockResolvedValue('not json')
    const result = await fetchAnnotations('owner/repo', '456', gh)
    expect(result).toEqual([])
  })

  it('never throws', async () => {
    const gh = vi.fn().mockRejectedValue(new Error('network error'))
    expect(async () => {
      await fetchAnnotations('owner/repo', '456', gh)
    }).not.toThrow()
  })
})

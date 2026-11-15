import { describe, it, expect, vi } from 'vitest'
import { guardApprove, runApprove } from '../electron/main/approve_guard.js'

// #215: the Approve click's own checks (dashboard side) record their refusal before it reaches the screen.
const url = (n) => `https://github.com/G-Eskayo/marvin/pull/${n}`
const pr = (n, ticket, files, extra = {}) => ({ number: n, url: url(n), repo: 'G-Eskayo/marvin', body: `Closes G-Eskayo/marvin#${ticket}`,
  files: files.map((path) => ({ path })), baseRefName: 'main', ...extra })

describe('guardApprove', () => {
  // marvin#231: "Merge #208 first" is gone: Approve queues the merge and the queue works out the order.
  it('an older PR on the same files is not a refusal any more: nothing recorded, the click goes on to the queue', async () => {
    const record = vi.fn()
    const prs = [pr(208, 161, ['a.js']), pr(209, 158, ['a.js'])]
    await guardApprove(url(209), { assertMergeable: () => {}, loadPrs: async () => prs, record })
    expect(record).not.toHaveBeenCalled()
  })

  it('a PR stacked on an open PR is not refused either: the queue merges its base first', async () => {
    const record = vi.fn()
    const prs = [pr(941, 932, ['a.js'], { headRefName: 'ticket/932' }), pr(942, 933, ['b.js'], { baseRefName: 'ticket/932' })]
    await guardApprove(url(942), { assertMergeable: () => {}, loadPrs: async () => prs, record })
    expect(record).not.toHaveBeenCalled()
  })

  it('records a base-check refusal as WRONG_BASE', async () => {
    const record = vi.fn()
    const prs = [pr(209, 158, ['a.js'], { baseRefName: 'feature' })]
    await expect(guardApprove(url(209), { assertMergeable: () => {}, loadPrs: async () => prs, record })).rejects.toThrow(/targets "feature"/)
    expect(record).toHaveBeenCalledWith(expect.objectContaining({ ticket: 158, code: 'WRONG_BASE' }))
  })

  it('records a project that has not opted in as NO_MERGE_PROFILE', async () => {
    const record = vi.fn()
    const notOptedIn = () => { throw Object.assign(new Error('not set up'), { code: 'NO_MERGE_PROFILE' }) }
    await expect(guardApprove(url(209), { assertMergeable: notOptedIn, loadPrs: async () => [], record })).rejects.toThrow(/not set up/)
    expect(record).toHaveBeenCalledWith(expect.objectContaining({ code: 'NO_MERGE_PROFILE', ticket: null }))
  })

  it('records nothing when the PR may be merged', async () => {
    const record = vi.fn()
    await guardApprove(url(209), { assertMergeable: () => {}, loadPrs: async () => [pr(209, 158, ['a.js'])], record })
    expect(record).not.toHaveBeenCalled()
  })

  it('a check that fails for some other reason is passed on, not recorded as a refusal', async () => {
    const record = vi.fn()
    await expect(guardApprove(url(209), { assertMergeable: () => {}, loadPrs: async () => { throw new Error('gh down') }, record })).rejects.toThrow('gh down')
    expect(record).not.toHaveBeenCalled()
  })
})

describe('runApprove', () => {
  it('calls guardApprove then approveFlow when both succeed', async () => {
    const result = { merged: true, reason: null }
    const approveFlow = vi.fn().mockResolvedValue(result)
    const r = await runApprove(url(209), { number: 209 }, {
      assertMergeable: () => {},
      loadPrs: async () => [pr(209, 158, ['a.js'])],
      record: vi.fn(),
      approveFlow
    })
    expect(r).toEqual(result)
    expect(approveFlow).toHaveBeenCalledWith(url(209), { number: 209 })
  })

  it('catches a guardApprove error and resolves to a structured failure shape', async () => {
    const approveFlow = vi.fn()
    const err = Object.assign(new Error('wrong base'), { code: 'WRONG_BASE' })
    const r = await runApprove(url(209), { number: 209 }, {
      assertMergeable: () => {},
      loadPrs: async () => [pr(209, 158, ['a.js'], { baseRefName: 'feature' })],
      record: vi.fn(),
      approveFlow
    })
    expect(r.merged).toBe(false)
    expect(r.code).toBe('WRONG_BASE')
    expect(r.message).toContain('targets "feature"')
    expect(r.remediation).toBeTruthy()
    expect(r.stage).toBe('request')
    expect(r.cancelled).toBe(false)
    expect(r.technicalDetails).toBe('WRONG_BASE')
    expect(approveFlow).not.toHaveBeenCalled()
  })

  it('catches an approveFlow error with a payload and resolves to a structured shape', async () => {
    const payload = { code: 'GH_AUTH_INVALID', stage: 'merging', message: 'Bad credentials' }
    const err = Object.assign(new Error('Auth failed'), { payload })
    const approveFlow = async () => { throw err }
    const r = await runApprove(url(209), { number: 209 }, {
      assertMergeable: () => {},
      loadPrs: async () => [pr(209, 158, ['a.js'])],
      record: vi.fn(),
      approveFlow
    })
    expect(r.merged).toBe(false)
    expect(r.code).toBe('GH_AUTH_INVALID')
    expect(r.message).toBe('Bad credentials')
    expect(r.stage).toBe('merging')
    expect(r.remediation).toContain('GitHub rejected the credential')
    expect(r.technicalDetails).toBe('GH_AUTH_INVALID')
  })

  it('catches an error without a payload and uses UNKNOWN', async () => {
    const err = new Error('Something went wrong')
    const approveFlow = async () => { throw err }
    const r = await runApprove(url(209), { number: 209 }, {
      assertMergeable: () => {},
      loadPrs: async () => [pr(209, 158, ['a.js'])],
      record: vi.fn(),
      approveFlow
    })
    expect(r.merged).toBe(false)
    expect(r.code).toBe('UNKNOWN')
    expect(r.message).toBe('Something went wrong')
    expect(r.stage).toBe('request')
    expect(r.remediation).toContain('Unclassified failure')
    expect(r.technicalDetails).toBe('UNKNOWN')
  })

  it('includes needsYou flag in the result when the code requires it', async () => {
    const payload = { code: 'GH_AUTH_INVALID', stage: 'merging', message: 'Bad credentials' }
    const err = Object.assign(new Error('Auth failed'), { payload })
    const approveFlow = async () => { throw err }
    const r = await runApprove(url(209), { number: 209 }, {
      assertMergeable: () => {},
      loadPrs: async () => [pr(209, 158, ['a.js'])],
      record: vi.fn(),
      approveFlow
    })
    expect(r.needsYou).toBe(true)
  })

  it('omits needsYou flag when the code does not require it', async () => {
    const payload = { code: 'BASE_MOVED', stage: 'merging', message: 'Base moved' }
    const err = Object.assign(new Error('Base moved'), { payload })
    const approveFlow = async () => { throw err }
    const r = await runApprove(url(209), { number: 209 }, {
      assertMergeable: () => {},
      loadPrs: async () => [pr(209, 158, ['a.js'])],
      record: vi.fn(),
      approveFlow
    })
    expect(r.needsYou).toBeUndefined()
  })
})

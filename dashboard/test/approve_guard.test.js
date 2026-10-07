import { describe, it, expect, vi } from 'vitest'
import { guardApprove } from '../electron/main/approve_guard.js'

// #215: the Approve click's own checks (dashboard side) record their refusal before it reaches the screen.
const url = (n) => `https://github.com/G-Eskayo/marvin/pull/${n}`
const pr = (n, ticket, files, extra = {}) => ({ number: n, url: url(n), repo: 'G-Eskayo/marvin', body: `Closes G-Eskayo/marvin#${ticket}`,
  files: files.map((path) => ({ path })), baseRefName: 'main', ...extra })

describe('guardApprove', () => {
  it('records an order-check refusal with the PR, its ticket and the OUT_OF_ORDER code', async () => {
    const record = vi.fn()
    const prs = [pr(208, 161, ['a.js']), pr(209, 158, ['a.js'])]
    await expect(guardApprove(url(209), { assertMergeable: () => {}, loadPrs: async () => prs, record })).rejects.toThrow(/Merge #208 first/)
    expect(record).toHaveBeenCalledWith(expect.objectContaining({ prUrl: url(209), ticket: 158, code: 'OUT_OF_ORDER', stage: 'request' }))
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

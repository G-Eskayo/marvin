import { describe, it, expect, vi } from 'vitest'
import { forwardRefreshPing } from '../webhook-server/refresh_relay.js'

describe('forwardRefreshPing', () => {
  it('posts to the given url with an empty body', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true })
    await forwardRefreshPing('http://localhost:7879/refresh', post)
    expect(post).toHaveBeenCalledWith('http://localhost:7879/refresh', {})
  })

  it('swallows a rejection instead of throwing', async () => {
    const post = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'))
    await expect(forwardRefreshPing('http://localhost:7879/refresh', post)).resolves.toBeUndefined()
  })
})

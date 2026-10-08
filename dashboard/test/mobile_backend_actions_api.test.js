import { describe, it, expect, vi } from 'vitest'
import { createActionsApiRouter } from '../mobile-backend/actions_api.js'

// Helper: parse JSON from response body
async function parseJsonBody(res) {
  let body = ''
  return new Promise((resolve) => {
    res.on('data', (chunk) => { body += chunk })
    res.on('end', () => { resolve(JSON.parse(body)) })
  })
}

// Helper: build a mock request/response pair
function createRequestResponse(method, pathname, body = null) {
  const chunks = body ? [JSON.stringify(body)] : []
  let chunkIndex = 0

  const req = {
    method,
    url: pathname,
    headers: { host: 'localhost:7880' },
    socket: { remoteAddress: '100.100.100.1' },
    [Symbol.asyncIterator]: async function* () {
      while (chunkIndex < chunks.length) {
        yield Buffer.from(chunks[chunkIndex++])
      }
    }
  }

  let statusCode = 200
  let headers = {}
  let responseBody = ''
  const res = {
    writeHead(code, h) {
      statusCode = code
      headers = h
      return this
    },
    end(data) {
      responseBody = data
    },
    statusCode: () => statusCode,
    headers: () => headers,
    body: () => responseBody,
    on(event, callback) {},
    data(callback) {
      callback(responseBody)
    }
  }

  return { req, res }
}

describe('createActionsApiRouter', () => {
  it('throws when required dependencies are missing', () => {
    expect(() => createActionsApiRouter({})).toThrow('required')
    expect(() => createActionsApiRouter({ postTicketInputFn: () => {} })).toThrow('required')
  })

  it('returns an async router function', () => {
    const router = createActionsApiRouter({
      postTicketInputFn: vi.fn(),
      approveMrFn: vi.fn(),
      denyMrFn: vi.fn(),
      postJson: vi.fn()
    })
    expect(typeof router).toBe('function')
  })
})

describe('POST /boards/ticket/reply', () => {
  const makeRouter = (overrides = {}) => createActionsApiRouter({
    postTicketInputFn: vi.fn().mockResolvedValue({ posted: true, requeued: true, effect: 'back to ready' }),
    approveMrFn: vi.fn(),
    denyMrFn: vi.fn(),
    postJson: vi.fn(),
    ...overrides
  })

  it('posts the comment and re-queues the ticket when confirmed=true', async () => {
    const postFn = vi.fn().mockResolvedValue({ posted: true, requeued: true, effect: 'back to ready' })
    const router = makeRouter({ postTicketInputFn: postFn })
    const { req, res } = createRequestResponse('POST', '/boards/ticket/reply', {
      repo: 'G-Eskayo/marvin',
      number: 42,
      body: 'Use option B',
      confirmed: true
    })

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode()).toBe(200)
    const body = JSON.parse(res.body())
    expect(body).toEqual({
      ok: true,
      data: { posted: true, requeued: true, effect: 'back to ready' }
    })
    expect(postFn).toHaveBeenCalledWith({
      repo: 'G-Eskayo/marvin',
      number: 42,
      body: 'Use option B'
    })
  })

  it('refuses when confirmed is missing (403, zero side effects)', async () => {
    const postFn = vi.fn()
    const router = makeRouter({ postTicketInputFn: postFn })
    const { req, res } = createRequestResponse('POST', '/boards/ticket/reply', {
      repo: 'G-Eskayo/marvin',
      number: 42,
      body: 'Use option B'
    })

    await router(req, res)

    expect(res.statusCode()).toBe(403)
    expect(postFn).not.toHaveBeenCalled()
  })

  it('refuses when confirmed is false (403, zero side effects)', async () => {
    const postFn = vi.fn()
    const router = makeRouter({ postTicketInputFn: postFn })
    const { req, res } = createRequestResponse('POST', '/boards/ticket/reply', {
      repo: 'G-Eskayo/marvin',
      number: 42,
      body: 'Use option B',
      confirmed: false
    })

    await router(req, res)

    expect(res.statusCode()).toBe(403)
    expect(postFn).not.toHaveBeenCalled()
  })

  it('returns 400 when postTicketInputFn throws', async () => {
    const postFn = vi.fn().mockRejectedValue(new Error('Not a G-Eskayo repo'))
    const router = makeRouter({ postTicketInputFn: postFn })
    const { req, res } = createRequestResponse('POST', '/boards/ticket/reply', {
      repo: 'someone/else',
      number: 42,
      body: 'text',
      confirmed: true
    })

    await router(req, res)

    expect(res.statusCode()).toBe(400)
    const body = JSON.parse(res.body())
    expect(body.ok).toBe(false)
    expect(body.error).toContain('repo')
  })

  it('returns 400 on invalid JSON', async () => {
    const router = makeRouter()
    const req = {
      method: 'POST',
      url: '/boards/ticket/reply',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield Buffer.from('invalid json')
      }
    }
    let statusCode = 200
    const res = {
      writeHead(s, h) {
        statusCode = s
        return this
      },
      end(d) {
        this.body = d
      },
      statusCode: () => statusCode
    }

    await router(req, res)

    expect(res.statusCode()).toBe(400)
  })

  it('returns parity with the real planInput requeue logic', async () => {
    // If the ticket has needs-info label, it should be re-queued
    const postFn = vi.fn().mockResolvedValue({
      posted: true,
      requeued: true,
      effect: 'back to ready, claim released'
    })
    const router = makeRouter({ postTicketInputFn: postFn })
    const { req, res } = createRequestResponse('POST', '/boards/ticket/reply', {
      repo: 'G-Eskayo/marvin',
      number: 12,
      body: 'FYI',
      confirmed: true
    })

    await router(req, res)

    const body = JSON.parse(res.body())
    expect(body.data.requeued).toBe(true)
  })

  it('returns warning if label change fails but comment posted', async () => {
    const postFn = vi.fn().mockResolvedValue({
      posted: true,
      requeued: false,
      effect: 'comment only',
      warning: 'Your comment is posted, but the ticket could not be moved back to ready'
    })
    const router = makeRouter({ postTicketInputFn: postFn })
    const { req, res } = createRequestResponse('POST', '/boards/ticket/reply', {
      repo: 'G-Eskayo/marvin',
      number: 12,
      body: 'The answer',
      confirmed: true
    })

    await router(req, res)

    const body = JSON.parse(res.body())
    expect(body.data.warning).toBeDefined()
  })
})

describe('POST /mr/approve', () => {
  const makeRouter = (overrides = {}) => createActionsApiRouter({
    postTicketInputFn: vi.fn(),
    approveMrFn: vi.fn().mockResolvedValue({ merged: true }),
    denyMrFn: vi.fn(),
    postJson: vi.fn(),
    ...overrides
  })

  it('approves and merges a PR when confirmed=true', async () => {
    const approveFn = vi.fn().mockResolvedValue({ merged: true })
    const postJson = vi.fn()
    const router = makeRouter({ approveMrFn: approveFn, postJson })
    const { req, res } = createRequestResponse('POST', '/mr/approve', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      confirmed: true
    })

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode()).toBe(200)
    const body = JSON.parse(res.body())
    expect(body).toEqual({
      ok: true,
      data: { merged: true }
    })
  })

  it('refuses when confirmed is missing (403, zero side effects)', async () => {
    const approveFn = vi.fn()
    const postJson = vi.fn()
    const router = makeRouter({ approveMrFn: approveFn, postJson })
    const { req, res } = createRequestResponse('POST', '/mr/approve', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71'
    })

    await router(req, res)

    expect(res.statusCode()).toBe(403)
    expect(approveFn).not.toHaveBeenCalled()
    expect(postJson).not.toHaveBeenCalled()
  })

  it('refuses when confirmed is false (403, zero side effects)', async () => {
    const approveFn = vi.fn()
    const postJson = vi.fn()
    const router = makeRouter({ approveMrFn: approveFn, postJson })
    const { req, res } = createRequestResponse('POST', '/mr/approve', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      confirmed: false
    })

    await router(req, res)

    expect(res.statusCode()).toBe(403)
    expect(approveFn).not.toHaveBeenCalled()
    expect(postJson).not.toHaveBeenCalled()
  })

  it('returns 500 when approveMr throws', async () => {
    const approveFn = vi.fn().mockRejectedValue(new Error('Merge conflict'))
    const router = makeRouter({ approveMrFn: approveFn })
    const { req, res } = createRequestResponse('POST', '/mr/approve', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      confirmed: true
    })

    await router(req, res)

    expect(res.statusCode()).toBe(500)
    const body = JSON.parse(res.body())
    expect(body.ok).toBe(false)
    expect(body.error).toContain('conflict')
  })

  it('returns the webhook response unchanged', async () => {
    const webhookResponse = { merged: false, reengaged: true, reason: 'Tests failed after rebasing' }
    const approveFn = vi.fn().mockResolvedValue(webhookResponse)
    const router = makeRouter({ approveMrFn: approveFn })
    const { req, res } = createRequestResponse('POST', '/mr/approve', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      confirmed: true
    })

    await router(req, res)

    const body = JSON.parse(res.body())
    expect(body.data).toEqual(webhookResponse)
  })
})

describe('POST /mr/deny', () => {
  const makeRouter = (overrides = {}) => createActionsApiRouter({
    postTicketInputFn: vi.fn(),
    approveMrFn: vi.fn(),
    denyMrFn: vi.fn().mockResolvedValue({ done: true }),
    postJson: vi.fn(),
    ...overrides
  })

  it('denies a PR with send_feedback action when confirmed=true', async () => {
    const denyFn = vi.fn().mockResolvedValue({ done: true })
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: 42,
      action: 'send_feedback',
      reasons: ['Insufficient tests'],
      comment: 'needs more coverage',
      confirmed: true
    })

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode()).toBe(200)
    const body = JSON.parse(res.body())
    expect(body.ok).toBe(true)
    expect(denyFn).toHaveBeenCalledWith(
      {
        prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
        ticketNumber: 42,
        action: 'send_feedback',
        reasons: ['Insufficient tests'],
        comment: 'needs more coverage'
      },
      expect.any(Function)
    )
  })

  it('denies a PR with drop action', async () => {
    const denyFn = vi.fn().mockResolvedValue({ done: true })
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: 42,
      action: 'drop',
      reasons: [],
      comment: '',
      confirmed: true
    })

    await router(req, res)

    expect(res.statusCode()).toBe(200)
    expect(denyFn).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'drop' }),
      expect.any(Function)
    )
  })

  it('refuses when confirmed is missing (403, zero side effects)', async () => {
    const denyFn = vi.fn()
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: 42,
      action: 'send_feedback',
      reasons: [],
      comment: ''
    })

    await router(req, res)

    expect(res.statusCode()).toBe(403)
    expect(denyFn).not.toHaveBeenCalled()
  })

  it('refuses when confirmed is false (403, zero side effects)', async () => {
    const denyFn = vi.fn()
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: 42,
      action: 'send_feedback',
      reasons: [],
      comment: '',
      confirmed: false
    })

    await router(req, res)

    expect(res.statusCode()).toBe(403)
    expect(denyFn).not.toHaveBeenCalled()
  })

  it('returns 400 for invalid action before any call', async () => {
    const denyFn = vi.fn()
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: 42,
      action: 'invalid_action',
      reasons: [],
      comment: '',
      confirmed: true
    })

    await router(req, res)

    expect(res.statusCode()).toBe(400)
    const body = JSON.parse(res.body())
    expect(body.error).toContain('action')
    expect(denyFn).not.toHaveBeenCalled()
  })

  it('returns 400 when action is missing', async () => {
    const denyFn = vi.fn()
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: 42,
      reasons: [],
      comment: '',
      confirmed: true
    })

    await router(req, res)

    expect(res.statusCode()).toBe(400)
    expect(denyFn).not.toHaveBeenCalled()
  })

  it('returns 500 when denyMr throws', async () => {
    const denyFn = vi.fn().mockRejectedValue(new Error('gh call failed'))
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: 42,
      action: 'send_feedback',
      reasons: ['Bad code'],
      comment: '',
      confirmed: true
    })

    await router(req, res)

    expect(res.statusCode()).toBe(500)
    const body = JSON.parse(res.body())
    expect(body.ok).toBe(false)
  })

  it('handles null ticket_number', async () => {
    const denyFn = vi.fn().mockResolvedValue({ done: true })
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: null,
      action: 'drop',
      reasons: [],
      comment: '',
      confirmed: true
    })

    await router(req, res)

    expect(res.statusCode()).toBe(200)
    expect(denyFn).toHaveBeenCalledWith(
      expect.objectContaining({ ticketNumber: null }),
      expect.any(Function)
    )
  })

  it('returns the webhook response unchanged', async () => {
    const webhookResponse = { done: true }
    const denyFn = vi.fn().mockResolvedValue(webhookResponse)
    const router = makeRouter({ denyMrFn: denyFn })
    const { req, res } = createRequestResponse('POST', '/mr/deny', {
      pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
      ticket_number: 42,
      action: 'send_feedback',
      reasons: [],
      comment: '',
      confirmed: true
    })

    await router(req, res)

    const body = JSON.parse(res.body())
    expect(body.data).toEqual(webhookResponse)
  })
})

describe('Unmatched routes', () => {
  const makeRouter = () => createActionsApiRouter({
    postTicketInputFn: vi.fn(),
    approveMrFn: vi.fn(),
    denyMrFn: vi.fn(),
    postJson: vi.fn()
  })

  it('returns false for unmatched routes', async () => {
    const router = makeRouter()
    const { req, res } = createRequestResponse('GET', '/unknown-route')

    const handled = await router(req, res)

    expect(handled).toBe(false)
  })

  it('returns false for wrong method on known route', async () => {
    const router = makeRouter()
    const { req, res } = createRequestResponse('GET', '/boards/ticket/reply')

    const handled = await router(req, res)

    expect(handled).toBe(false)
  })
})

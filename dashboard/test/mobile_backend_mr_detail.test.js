import { describe, it, expect, vi } from 'vitest'
import { createDashboardApiRouter } from '../mobile-backend/dashboard_api.js'

// Helper: parse JSON from response body
async function parseJsonBody(res) {
  let body = ''
  return new Promise((resolve) => {
    res.on('data', (chunk) => { body += chunk })
    res.on('end', () => { resolve(JSON.parse(body)) })
  })
}

// Helper: build a mock request/response pair
function createRequestResponse(method, pathname, search = '') {
  const url = search ? `${pathname}?${search}` : pathname
  const req = {
    method,
    url,
    headers: { host: 'localhost:7880' },
    socket: { remoteAddress: '100.100.100.1' }
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
    },
    createReadStream() {
      return { pipe: () => {} }
    }
  }

  return { req, res }
}

describe('GET /mr/<owner>/<name>/<number> - PR detail', () => {
  const makeRouter = (overrides = {}) => createDashboardApiRouter({
    exec: vi.fn(),
    registryPath: '/tmp/registry.json',
    mrMediaCacheDir: '/tmp/mr-media-cache',
    ...overrides
  })

  it('case 4: returns full PR detail with parsed images and ticketRef', async () => {
    const execMock = vi.fn().mockResolvedValue({
      stdout: JSON.stringify({
        number: 42,
        title: 'Test PR',
        url: 'https://github.com/G-Eskayo/marvin/pull/42',
        headRefName: 'feature/test',
        body: 'Closes #100\n\n![test](image.png)',
        files: [{ path: 'src/test.js' }]
      })
    })
    const router = makeRouter({ exec: execMock })
    const { req, res } = createRequestResponse('GET', '/mr/G-Eskayo/marvin/42')

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode()).toBe(200)
    const body = JSON.parse(res.body())
    expect(body.ok).toBe(true)
    expect(body.data.number).toBe(42)
    expect(body.data.title).toBe('Test PR')
    expect(body.data.ticketRef).toBe('100')
    expect(body.data.images).toBeInstanceOf(Array)
  })

  it('case 5: non-numeric number segment returns 400/unmatched', async () => {
    const router = makeRouter()
    const { req, res } = createRequestResponse('GET', '/mr/G-Eskayo/marvin/1; rm -rf')

    const handled = await router(req, res)

    expect(handled).toBe(false)
  })

  it('case 6: path with missing segments returns unmatched', async () => {
    const router = makeRouter()
    const { req, res } = createRequestResponse('GET', '/mr/G-Eskayo/42')

    const handled = await router(req, res)

    expect(handled).toBe(false)
  })

  it('case 6b: path with traversal attempt returns unmatched', async () => {
    const router = makeRouter()
    const { req, res } = createRequestResponse('GET', '/mr/G-Eskayo/../marvin/42')

    const handled = await router(req, res)

    expect(handled).toBe(false)
  })

  it('case 7: repo not in registry returns 403', async () => {
    const router = makeRouter({
      registryPath: '/tmp/empty-registry.json'
    })
    const { req, res } = createRequestResponse('GET', '/mr/private-repo/private-name/42')

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode()).toBe(403)
    const body = JSON.parse(res.body())
    expect(body.ok).toBe(false)
    expect(body.error).toContain('not authorized')
  })

  it('case 8: gh execution error bubbles as 500', async () => {
    const execMock = vi.fn().mockRejectedValue(new Error('gh: not found'))
    const router = makeRouter({ exec: execMock })
    const { req, res } = createRequestResponse('GET', '/mr/G-Eskayo/marvin/42')

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode()).toBe(500)
    const body = JSON.parse(res.body())
    expect(body.ok).toBe(false)
  })

  it('case 9: empty PR body returns empty images array', async () => {
    const execMock = vi.fn().mockResolvedValue({
      stdout: JSON.stringify({
        number: 42,
        title: 'Empty PR',
        url: 'https://github.com/G-Eskayo/marvin/pull/42',
        headRefName: 'feature/test',
        body: '',
        files: []
      })
    })
    const router = makeRouter({ exec: execMock })
    const { req, res } = createRequestResponse('GET', '/mr/G-Eskayo/marvin/42')

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode()).toBe(200)
    const body = JSON.parse(res.body())
    expect(body.data.images).toEqual([])
    expect(body.data.ticketRef).toBeNull()
  })

  it('case 20: needsImages field present and correct for UI changes without images', async () => {
    const execMock = vi.fn().mockResolvedValue({
      stdout: JSON.stringify({
        number: 42,
        title: 'UI change',
        url: 'https://github.com/G-Eskayo/marvin/pull/42',
        headRefName: 'feature/test',
        body: 'UI changes here',
        files: [
          { path: 'src/components/Button.jsx' },
          { path: 'src/styles/button.css' }
        ]
      })
    })
    const router = makeRouter({
      exec: execMock,
      MARVIN_REPO: 'G-Eskayo/marvin'
    })
    const { req, res } = createRequestResponse('GET', '/mr/G-Eskayo/marvin/42')

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode()).toBe(200)
    const body = JSON.parse(res.body())
    expect(body.data.needsImages).not.toBeNull()
    expect(body.data.needsImages.files).toBeDefined()
  })
})

import { describe, it, expect, afterEach } from 'vitest'
import { createServer } from 'http'
import { createPortfolioProxy, handlePortfolioRequest, portfolioHost } from '../electron/main/portfolio_remote.js'

// ADR 0036: the Portfolio backend runs only on the dev host; other machines call it through a proxy with the same
// method names, over the webhook server's POST /portfolio/<method>.

let server
afterEach(() => new Promise((r) => (server ? server.close(r) : r())))

// A real HTTP round trip: proxy -> handler -> backend, exactly as the webhook server wires it.
function serve(backend) {
  server = createServer((req, res) => {
    let body = ''
    req.on('data', (c) => (body += c))
    req.on('end', async () => {
      const { status, json } = await handlePortfolioRequest(backend, req.url, body)
      res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(json))
    })
  })
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${server.address().port}/portfolio`)))
}

describe('the proxy behaves like the backend it stands in for', () => {
  it('passes arguments through and returns the result', async () => {
    const backend = { chooseImageVariant: async (slug, motif, salt) => ({ slug, motif, salt, chosen: true }) }
    const proxy = createPortfolioProxy({ baseUrl: await serve(backend), methods: Object.keys(backend) })
    expect(await proxy.chooseImageVariant('mancala', 'rings', 7)).toEqual({ slug: 'mancala', motif: 'rings', salt: 7, chosen: true })
  })

  it('carries null and missing results (a not-yet-run evaluation is null, not an error)', async () => {
    const backend = { latestEval: async () => null, getGuide: async () => '' }
    const proxy = createPortfolioProxy({ baseUrl: await serve(backend), methods: Object.keys(backend) })
    expect(await proxy.latestEval()).toBeNull()
    expect(await proxy.getGuide()).toBe('')
  })

  it("rethrows the backend's own error message, so the tab shows the same text it would locally", async () => {
    const backend = { addProject: async () => { throw new Error('The slug must be lowercase letters, digits and hyphens') } }
    const proxy = createPortfolioProxy({ baseUrl: await serve(backend), methods: Object.keys(backend) })
    await expect(proxy.addProject({ slug: 'Bad Slug' })).rejects.toThrow('The slug must be lowercase letters, digits and hyphens')
  })

  it('names the dev host when it cannot be reached', async () => {
    const proxy = createPortfolioProxy({ baseUrl: 'http://127.0.0.1:1/portfolio', methods: ['inventory'] })
    await expect(proxy.inventory()).rejects.toThrow(/dev host.*127\.0\.0\.1:1/i)
  })

  it('gives up after its timeout instead of hanging the tab', async () => {
    const backend = { runEval: () => new Promise(() => {}) }
    const proxy = createPortfolioProxy({ baseUrl: await serve(backend), methods: Object.keys(backend), timeoutMs: 200 })
    await expect(proxy.runEval()).rejects.toThrow(/timed out/i)
  })
})

describe('the handler only runs the backend\'s own methods', () => {
  const backend = { inventory: async () => ({ pages: 3 }), notAFunction: 42 }

  it('rejects an unknown method', async () => {
    expect(await handlePortfolioRequest(backend, '/portfolio/constructor', '{"args":[]}')).toMatchObject({ status: 404 })
    expect(await handlePortfolioRequest(backend, '/portfolio/notAFunction', '{"args":[]}')).toMatchObject({ status: 404 })
    expect(await handlePortfolioRequest(backend, '/portfolio/__proto__', '{"args":[]}')).toMatchObject({ status: 404 })
  })

  it('rejects a body that is not JSON with an args array', async () => {
    expect(await handlePortfolioRequest(backend, '/portfolio/inventory', 'nope')).toMatchObject({ status: 400 })
    expect(await handlePortfolioRequest(backend, '/portfolio/inventory', '{"args":"x"}')).toMatchObject({ status: 400 })
  })

  it('treats an empty body as no arguments', async () => {
    expect(await handlePortfolioRequest(backend, '/portfolio/inventory', '')).toEqual({ status: 200, json: { ok: true, result: { pages: 3 } } })
  })
})

describe('which machine runs the backend', () => {
  it('is this machine when the dev host is localhost (the primary host itself)', () => {
    expect(portfolioHost({ env: {}, defaultHost: 'localhost' })).toEqual({ local: true, host: 'localhost' })
  })

  it("is the primary host otherwise, and MARVIN_PORTFOLIO_HOST overrides it when the dev site moves", () => {
    expect(portfolioHost({ env: {}, defaultHost: 'gils-mac-mini' })).toEqual({ local: false, host: 'gils-mac-mini' })
    expect(portfolioHost({ env: { MARVIN_PORTFOLIO_HOST: 'localhost' }, defaultHost: 'gils-mac-mini' })).toEqual({ local: true, host: 'localhost' })
    expect(portfolioHost({ env: { MARVIN_PORTFOLIO_HOST: 'other-box' }, defaultHost: 'localhost' })).toEqual({ local: false, host: 'other-box' })
  })
})

import http from 'http'

// ADR 0036: the Portfolio tab's backend (portfolio.js) runs only on the dev host, the machine the dev site runs on. The
// webhook server there exposes it as POST /portfolio/<method> {args}; every other machine's dashboard uses a proxy with
// the same method names. Nothing per-method lives here, so a new backend method works remotely as soon as it exists.

const PREFIX = '/portfolio/'
// Evaluation and add-project runs take up to 15 minutes on the dev host (portfolio.js's own exec timeouts).
const DEFAULT_TIMEOUT_MS = 16 * 60 * 1000

// Which machine runs the backend: the primary host by default (ADR 0032), or MARVIN_PORTFOLIO_HOST when the dev site
// has moved (portfolio repo ADR 0003: it runs on one machine at a time).
export function portfolioHost({ env = process.env, defaultHost = 'localhost' } = {}) {
  const host = env.MARVIN_PORTFOLIO_HOST || defaultHost
  return { local: host === 'localhost', host }
}

export async function handlePortfolioRequest(backend, url, body) {
  const method = String(url || '').startsWith(PREFIX) ? decodeURIComponent(String(url).slice(PREFIX.length)) : ''
  if (!Object.prototype.hasOwnProperty.call(backend, method) || typeof backend[method] !== 'function') {
    return { status: 404, json: { ok: false, error: `Unknown portfolio method: ${JSON.stringify(method)}` } }
  }
  let args = []
  if (String(body || '').trim()) {
    try {
      args = JSON.parse(body).args
    } catch {
      args = null
    }
    if (!Array.isArray(args)) return { status: 400, json: { ok: false, error: 'Body must be JSON: {"args": [...]}' } }
  }
  try {
    const result = await backend[method](...args)
    return { status: 200, json: { ok: true, result: result === undefined ? null : result } }
  } catch (err) {
    return { status: 500, json: { ok: false, error: String(err?.message || err) } }
  }
}

// A plain http.request, not fetch: fetch stops waiting for response headers after 300s, and long runs exceed that.
function postJson(url, payload, timeoutMs, request = http.request) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(payload)
    const req = request(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } }, (res) => {
      let text = ''
      res.setEncoding('utf8')
      res.on('data', (c) => (text += c))
      res.on('end', () => resolve({ status: res.statusCode, text }))
      res.on('error', reject)
    })
    req.setTimeout(timeoutMs, () => req.destroy(new Error(`timed out after ${Math.round(timeoutMs / 1000)}s`)))
    req.on('error', reject)
    req.end(data)
  })
}

export function createPortfolioProxy({ baseUrl, methods, timeoutMs = DEFAULT_TIMEOUT_MS, request } = {}) {
  const root = String(baseUrl).replace(/\/+$/, '')
  const call = async (method, args) => {
    let res
    try {
      res = await postJson(`${root}/${encodeURIComponent(method)}`, { args }, timeoutMs, request)
    } catch (err) {
      const why = /timed out/.test(err.message) ? err.message : `could not reach the dev host at ${root}: ${err.message}`
      throw new Error(`Portfolio ${method}: ${why}`)
    }
    let json
    try {
      json = JSON.parse(res.text)
    } catch {
      throw new Error(`Portfolio ${method}: the dev host answered HTTP ${res.status} without JSON (is its webhook server up to date?)`)
    }
    if (!json.ok) throw new Error(json.error || `Portfolio ${method} failed (HTTP ${res.status})`)
    return json.result
  }
  return Object.fromEntries(methods.map((m) => [m, (...args) => call(m, args)]))
}

// GET /copy/<name> (marvin#1223): a Mac serves its own stamped copies to its peers, so a standby Mac shows the
// producer's live copy ("Mac mini, as of 2 min ago") instead of its own frozen one. Outward-facing, so it is attacked
// (ADR 0063): only loopback and Tailscale addresses, only GET, only four named files, no traversal, no oversized body,
// nothing but the file's JSON in the reply.
import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { copyRoute, COPY_NAMES } from '../webhook-server/copy_route.js'

const dir = mkdtempSync(join(tmpdir(), 'copy-'))
const paths = Object.fromEntries(COPY_NAMES.map((n) => [n, join(dir, `${n}.json`)]))
writeFileSync(paths['health-status'], JSON.stringify({ host: 'mac-mini-1', generated_at: '2026-11-10T12:00:00Z', tolerance_s: 1200, checks: [] }))

function call({ method = 'GET', url, ip = '100.101.1.2', maxBytes } = {}) {
  const res = { status: null, headers: null, body: null, writeHead(s, h) { this.status = s; this.headers = h; return this }, end(b) { this.body = b; return this } }
  const handled = copyRoute({ method, url, socket: { remoteAddress: ip } }, res, { paths, maxBytes })
  return { handled, ...res }
}

describe('GET /copy/<name>', () => {
  it('serves a named copy to a Tailscale peer, as the file says', () => {
    const r = call({ url: '/copy/health-status' })
    expect(r.handled).toBe(true)
    expect(r.status).toBe(200)
    expect(r.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(r.body)).toMatchObject({ host: 'mac-mini-1', tolerance_s: 1200 })
  })

  it('serves loopback too (this Mac\'s own dashboard)', () => {
    expect(call({ url: '/copy/health-status', ip: '::ffff:127.0.0.1' }).status).toBe(200)
  })

  it.each(['192.168.1.20', '10.0.0.5', '100.63.0.1', '100.128.0.1', '8.8.8.8', '', null])('refuses %s (LAN, outside the Tailscale range, none)', (ip) => {
    const r = call({ url: '/copy/health-status', ip })
    expect(r.status).toBe(403)
    expect(r.body).not.toContain('mac-mini-1')
  })

  it.each(['/copy/../../.ssh/id_ed25519', '/copy/%2e%2e%2fsecrets', '/copy/health-status.json', '/copy/HEALTH-STATUS', '/copy/', '/copy/health-status/x'])('404s anything but the four names: %s', (url) => {
    const r = call({ url })
    expect(r.handled).toBe(true)
    expect([404, 400]).toContain(r.status)
    expect(r.body || '').not.toContain('mac-mini-1')
  })

  it('a query string is ignored, not a way round the name check', () => {
    expect(call({ url: '/copy/health-status?cache=no' }).status).toBe(200)
  })

  it('only GET: a POST or DELETE is 405', () => {
    expect(call({ method: 'POST', url: '/copy/health-status' }).status).toBe(405)
    expect(call({ method: 'DELETE', url: '/copy/health-status' }).status).toBe(405)
  })

  it('a missing file is 404, a file that is not a JSON object is 502, never its raw text', () => {
    expect(call({ url: '/copy/dispatch-state' }).status).toBe(404)
    writeFileSync(paths['ticket-agent-proposals'], 'not json <script>')
    const r = call({ url: '/copy/ticket-agent-proposals' })
    expect(r.status).toBe(502)
    expect(r.body).not.toContain('<script>')
  })

  it('an oversized file is refused (413), not streamed', () => {
    writeFileSync(paths['boards-registry'], JSON.stringify({ boards: [], pad: 'x'.repeat(5000) }))
    expect(call({ url: '/copy/boards-registry', maxBytes: 1000 }).status).toBe(413)
  })

  it('leaves every other URL to the other routes', () => {
    expect(call({ url: '/approve' }).handled).toBe(false)
    expect(call({ url: '/copycat' }).handled).toBe(false)
  })
})

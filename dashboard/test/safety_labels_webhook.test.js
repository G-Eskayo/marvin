import { describe, it, expect } from 'vitest'
import { handleSafetyRequest, safetyLabelSource } from '../webhook-server/safety_labels.js'

// The primary host's end of the shared safety calibration. Labels arrive from other Macs over the network, so the
// route is attacked: bad JSON, arrays, extra fields, shell text, an invalid label, a failing script.

const ok = (stdout) => { const calls = []; return { calls, run: async (args) => (calls.push(args), stdout) } }

describe('POST /safety/label', () => {
  it('passes only the known fields, as one argv item', async () => {
    const r = ok('{"ok": true, "recorded": true, "taus": {"*": 0.3}}')
    const res = await handleSafetyRequest({ method: 'POST', url: '/safety/label', body: JSON.stringify({ loop: 'daily_digest', score: 0.4, label: 1, entry_id: 'a'.repeat(16), cmd: '$(rm -rf ~)', __proto__: { x: 1 } }) }, r.run)
    expect(res).toEqual({ status: 200, json: { ok: true, recorded: true, taus: { '*': 0.3 } } })
    expect(r.calls).toEqual([['record', JSON.stringify({ loop: 'daily_digest', score: 0.4, label: 1, entry_id: 'a'.repeat(16) })]])
  })

  it.each(['', 'not json', '[1,2]', 'null', '"str"'])('refuses body %j without running anything', async (body) => {
    const r = ok('{}')
    expect((await handleSafetyRequest({ method: 'POST', url: '/safety/label', body }, r.run)).status).toBe(400)
    expect(r.calls).toEqual([])
  })

  it('an invalid label is a 422 with the script’s reason', async () => {
    const run = async () => { const e = new Error('exit 1'); e.stdout = '{"ok": false, "error": "invalid label: loop"}'; throw e }
    expect(await handleSafetyRequest({ method: 'POST', url: '/safety/label', body: '{"loop":"../x"}' }, run)).toEqual({ status: 422, json: { ok: false, error: 'invalid label: loop' } })
  })

  it('a script that fails or prints garbage is a 500, never a throw', async () => {
    expect((await handleSafetyRequest({ method: 'POST', url: '/safety/label', body: '{}' }, async () => { throw new Error('python missing') })).status).toBe(500)
    expect((await handleSafetyRequest({ method: 'POST', url: '/safety/label', body: '{}' }, async () => 'Traceback')).status).toBe(500)
  })

  it('other methods and paths are 404', async () => {
    const r = ok('{}')
    expect((await handleSafetyRequest({ method: 'GET', url: '/safety/label', body: '' }, r.run)).status).toBe(404)
    expect((await handleSafetyRequest({ method: 'POST', url: '/safety/taus', body: '' }, r.run)).status).toBe(404)
    expect(r.calls).toEqual([])
  })
})

describe('GET /safety/taus', () => {
  it('returns the map', async () => {
    expect(await handleSafetyRequest({ method: 'GET', url: '/safety/taus' }, async () => '{"*": 0.3, "daily_digest": 0.6}')).toEqual({ status: 200, json: { '*': 0.3, daily_digest: 0.6 } })
  })
  it('a failing script is a 500', async () => {
    expect((await handleSafetyRequest({ method: 'GET', url: '/safety/taus' }, async () => { throw new Error('x') })).status).toBe(500)
  })
})

// ADR 0074: verify safety label submissions come from registered Macs
describe('safetyLabelSource', () => {
  const mockWhois = async (ip) => {
    if (ip === '192.168.1.10') return 'mac-mini-1'
    if (ip === '192.168.1.20') return 'macbook'
    return null
  }
  const mockMacHosts = () => ['mac-mini-1.some.domain', 'macbook.some.domain']
  const mockIsAllowed = (peer, hosts) => hosts.some(h => h.startsWith(peer))

  it('returns loopback for localhost addresses', async () => {
    expect(await safetyLabelSource('127.0.0.1', { whois: mockWhois, macHosts: mockMacHosts, isAllowed: mockIsAllowed })).toBe('loopback')
    expect(await safetyLabelSource('::1', { whois: mockWhois, macHosts: mockMacHosts, isAllowed: mockIsAllowed })).toBe('loopback')
    expect(await safetyLabelSource('::ffff:127.0.0.1', { whois: mockWhois, macHosts: mockMacHosts, isAllowed: mockIsAllowed })).toBe('loopback')
  })

  it('resolves via whois and matches against registered Macs', async () => {
    const source = await safetyLabelSource('192.168.1.10', { whois: mockWhois, macHosts: mockMacHosts, isAllowed: mockIsAllowed })
    expect(source).toBe('mac-mini-1')
  })

  it('returns null for unknown or unregistered addresses', async () => {
    const mockMacHostsEmpty = () => []
    expect(await safetyLabelSource('192.168.1.99', { whois: mockWhois, macHosts: mockMacHostsEmpty, isAllowed: mockIsAllowed })).toBe(null)
  })

  it('returns null when there is no remote address', async () => {
    expect(await safetyLabelSource(null, { whois: mockWhois, macHosts: mockMacHosts, isAllowed: mockIsAllowed })).toBe(null)
  })
})

describe('handleSafetyRequest with source', () => {
  it('adds verified source to the label payload', async () => {
    const r = ok('{"ok": true, "recorded": true, "taus": {"*": 0.3}}')
    const res = await handleSafetyRequest(
      { method: 'POST', url: '/safety/label', body: JSON.stringify({ loop: 'test', score: 0.5, label: 0 }), source: 'mac-mini-1' },
      r.run
    )
    expect(res).toEqual({ status: 200, json: { ok: true, recorded: true, taus: { '*': 0.3 } } })
    expect(r.calls).toHaveLength(1)
    expect(r.calls[0][1]).toContain('"source":"mac-mini-1"')
  })

  it('discards client-supplied source and uses verified one', async () => {
    const r = ok('{"ok": true, "recorded": true, "taus": {"*": 0.3}}')
    const res = await handleSafetyRequest(
      { method: 'POST', url: '/safety/label', body: JSON.stringify({ loop: 'test', score: 0.5, label: 0, source: 'fake-source' }), source: 'mac-mini-1' },
      r.run
    )
    expect(r.calls).toHaveLength(1)
    expect(r.calls[0][1]).toContain('"source":"mac-mini-1"')
    expect(r.calls[0][1]).not.toContain('fake-source')
  })
})

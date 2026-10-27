import { describe, it, expect } from 'vitest'
import { handleSafetyRequest } from '../webhook-server/safety_labels.js'

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

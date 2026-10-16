// node --test brain-map/desktop-live-linux/host.test.js   (also run from lib/tests/test_desktop_live_linux.py)
'use strict'
const test = require('node:test')
const assert = require('node:assert')
const vm = require('node:vm')
const h = require('./host.js')

// Run generated JS against a fake page and record what was called, exactly as the real page would receive it.
function runOnPage(js) {
  const got = []
  const window = {}
  for (const fn of ['triggerActivity', 'demoAddNode', 'demoRemoveNode', 'updateTreeData', 'setDeviceStatus']) {
    window[fn] = (...args) => got.push(JSON.parse(JSON.stringify([fn, ...args])))   // plain data: the page runs in another realm
  }
  vm.runInNewContext(js, { window })
  return got
}

test('a hostile skill name arrives as plain text and runs nothing', () => {
  const evil = "x'); window.pwned = 1; ('"
  const [js] = h.activityCalls([JSON.stringify({ skill: evil })])
  const ctx = { window: { triggerActivity: (s) => { ctx.got = s } } }
  vm.runInNewContext(js, ctx)
  assert.strictEqual(ctx.got, evil)
  assert.strictEqual(ctx.window.pwned, undefined)
})

test('only new lines count, and a trimmed file starts over', () => {
  assert.deepStrictEqual(h.newLines('a\nb\n', 0), { lines: ['a', 'b'], count: 2 })
  assert.deepStrictEqual(h.newLines('a\nb\nc\n', 2), { lines: ['c'], count: 3 })
  assert.deepStrictEqual(h.newLines('z\n', 3), { lines: [], count: 1 })
  assert.deepStrictEqual(h.newLines('', 0), { lines: [], count: 0 })
})

test('bad activity lines are skipped, good ones fire', () => {
  const calls = h.activityCalls(['not json', '{"no_skill": 1}', '{"skill": 7}', '{"skill": "tdd"}'])
  assert.deepStrictEqual(calls.flatMap(runOnPage), [['triggerActivity', 'tdd']])
})

test('demo add and remove reach the page with their data intact', () => {
  const calls = h.demoCalls([
    JSON.stringify({ type: 'add', node: { id: 'n1', name: 'New' }, parent: 'root' }),
    JSON.stringify({ type: 'remove', id: 'n1' }),
    JSON.stringify({ type: 'add', node: { id: 'n2' } }),          // no parent: skipped
    'garbage',
  ])
  assert.deepStrictEqual(calls.flatMap(runOnPage), [
    ['demoAddNode', { id: 'n1', name: 'New' }, 'root'],
    ['demoRemoveNode', 'n1'],
  ])
})

test('tree data that does not parse asks for a reload instead of going stale', () => {
  assert.strictEqual(h.treeCall('{"tree": {"a": 1'), null)
  assert.deepStrictEqual(runOnPage(h.treeCall('{"tree": {"a": 1}, "synapses": [1]}')), [['updateTreeData', { a: 1 }, [1]]])
  assert.deepStrictEqual(runOnPage(h.treeCall('{}')), [['updateTreeData', {}, []]])
})

test('device liveness only reports changes, matches on the hostname prefix, and treats missing as offline', () => {
  const registry = { devices: { 'mac-mini-1': { tailscale_hostname: 'gils-mac-mini' },
                                'mac-mini-2012': { tailscale_hostname: 'mac-mini-2012' },
                                'macbook-pro-1': { tailscale_hostname: 'laptop' } } }
  const status = { Self: { DNSName: 'mac-mini-2012.tail1234.ts.net.', Online: true },
                   Peer: { a: { DNSName: 'gils-mac-mini.tail1234.ts.net.', Online: true } } }
  const first = h.livenessCalls(status, registry, {})
  assert.deepStrictEqual(first.calls.flatMap(runOnPage).sort(), [
    ['setDeviceStatus', 'mac-mini-1', true], ['setDeviceStatus', 'mac-mini-2012', true],
    ['setDeviceStatus', 'macbook-pro-1', false]].sort())
  assert.deepStrictEqual(h.livenessCalls(status, registry, first.last).calls, [])
  assert.deepStrictEqual(h.livenessCalls(null, null, {}).calls, [])
})

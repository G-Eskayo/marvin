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
  for (const fn of ['triggerActivity', 'demoAddNode', 'demoRemoveNode', 'updateTreeData', 'setDeviceStatus', 'applyWork']) {
    window[fn] = (...args) => got.push(JSON.parse(JSON.stringify([fn, ...args])))   // plain data: the page runs in another realm
  }
  vm.runInNewContext(js, { window })
  return got
}

test('a hostile skill name arrives as plain text and runs nothing', () => {
  const evil = "x'); window.pwned = 1; ('"
  const [js] = h.activityCalls([JSON.stringify({ skill: evil })])
  const ctx = { window: { triggerActivity: (o) => { ctx.got = o.skill } } }
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
  assert.deepStrictEqual(calls.flatMap(runOnPage), [['triggerActivity', { skill: 'tdd' }]])
})

// #843: the page pairs a skill call with the next event in its session, so the whole line reaches it, not just
// the skill id. Only the fields the page reads are passed, each only with the type it expects.
test('the whole activity line reaches the page, limited to the fields it reads', () => {
  const line = { skill: 'MARVIN', ts: 1.5, tool: 'Edit', session: 's1', file: 'skills/tdd/SKILL.md', ok: false, extra: 'x' }
  assert.deepStrictEqual(h.activityCalls([JSON.stringify(line)]).flatMap(runOnPage),
    [['triggerActivity', { skill: 'MARVIN', ts: 1.5, tool: 'Edit', session: 's1', file: 'skills/tdd/SKILL.md', ok: false }]])
  const odd = { skill: 'tdd', ts: 'soon', tool: 3, session: null, file: ['a'], ok: 'yes' }
  assert.deepStrictEqual(h.activityCalls([JSON.stringify(odd)]).flatMap(runOnPage), [['triggerActivity', { skill: 'tdd' }]])
})

// #843: activity.jsonl is trimmed to its last 500 lines on every write, so once it is full the count never
// grows and a count-based reader saw nothing new again. Activity is read by the last line seen instead.
test('activity lines are found after the last line seen, even when the file is full and trimmed', () => {
  const full = Array.from({ length: 500 }, (_, i) => `{"skill":"MARVIN","ts":${i}}`)
  const start = h.linesAfter(full.join('\n') + '\n', null, true)
  assert.deepStrictEqual(start, { lines: [], last: full[499] }, 'history replayed at start')
  const trimmed = full.slice(1).concat(['{"skill":"tdd","ts":500}'])
  assert.deepStrictEqual(h.linesAfter(trimmed.join('\n') + '\n', start.last), { lines: ['{"skill":"tdd","ts":500}'], last: trimmed[499] })
  assert.deepStrictEqual(h.linesAfter(trimmed.join('\n') + '\n', trimmed[499]), { lines: [], last: trimmed[499] })
  // The last line seen is gone (the file was replaced): everything in it is new.
  assert.deepStrictEqual(h.linesAfter('a\nb\n', 'zzz'), { lines: ['a', 'b'], last: 'b' })
  // Emptied, then written again.
  assert.deepStrictEqual(h.linesAfter('', 'b'), { lines: [], last: 'b' })
  assert.deepStrictEqual(h.linesAfter('c\n', 'b'), { lines: ['c'], last: 'c' })
  // Nothing seen yet (no file at start): all lines are new.
  assert.deepStrictEqual(h.linesAfter('a\n', null), { lines: ['a'], last: 'a' })
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
  assert.deepStrictEqual(runOnPage(h.treeCall('{"tree": {"a": 1}, "synapses": [1]}')), [['updateTreeData', { a: 1 }, [1], null]])
  assert.deepStrictEqual(runOnPage(h.treeCall('{}')), [['updateTreeData', {}, [], null]])
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

// ── #854 parity: the wallpaper shows the same Body and Work layout and data as the browser page ──

test('tree data carries the Body and Work layout through to the page', () => {
  const work = { tree: { id: 'MARVIN', children: [] }, synapses: [2] }
  assert.deepStrictEqual(runOnPage(h.treeCall(JSON.stringify({ tree: { a: 1 }, synapses: [1], work }))),
    [['updateTreeData', { a: 1 }, [1], work]])
  assert.deepStrictEqual(runOnPage(h.treeCall('{"tree": {"a": 1}, "synapses": []}')), [['updateTreeData', { a: 1 }, [], null]])
})

test('work.json reaches the page as one applyWork call, and junk reaches nothing', () => {
  const doc = { workers: [{ id: 'helper:a1', state: 'running', project: null }], projects: [] }
  const got = []
  vm.runInNewContext(h.workCall(JSON.stringify(doc)), { window: { applyWork: (d) => got.push(JSON.parse(JSON.stringify(d))) } })
  assert.deepStrictEqual(got, [doc])
  for (const bad of ['', '{', '[]', '{"workers": 3}', 'null']) assert.strictEqual(h.workCall(bad), null, bad)
})

test('a helper id on an activity line reaches the page, so the wallpaper lights that worker', () => {
  assert.deepStrictEqual(h.activityCalls([JSON.stringify({ skill: 'MARVIN', agent: 'a1', extra: 1 })]).flatMap(runOnPage),
    [['triggerActivity', { skill: 'MARVIN', agent: 'a1' }]])
})

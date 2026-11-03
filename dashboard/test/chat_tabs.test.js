import { describe, it, expect } from 'vitest'
import http from 'http'
import { createChatsReader, fetchChatsFrom, parseLocal } from '../electron/main/chat_tabs.js'

// marvin#1064: the live chat tabs on this Mac and the other one, for the dashboard. Never an empty list that hides
// work: WezTerm down and the other Mac unreachable are states, and the other Mac's chats are read-only.

const chat = (over = {}) => ({ mac: 'macbook-pro', pane: 16, ticket: 1064, repo: 'G-Eskayo/marvin', state: 'working',
  title: '◐ chat list', unknown: false, cwd: '/wt/x', socket: '/s/gui-sock-1', tty: 'ttys004', ...over })

const local = (out) => async () => out

describe('this Mac', () => {
  it('lists its chats with focus and send allowed', async () => {
    const read = createChatsReader({ listLocal: local({ wezterm: true, chats: [chat()] }), peers: () => [] })
    const { macs } = await read()
    expect(macs[0]).toMatchObject({ here: true, status: 'ok' })
    expect(macs[0].chats[0]).toMatchObject({ pane: 16, ticket: 1064, state: 'working', canFocus: true, canSend: true })
  })

  it('says WezTerm is not running instead of an empty list', async () => {
    const read = createChatsReader({ listLocal: local({ wezterm: false, chats: [] }), peers: () => [] })
    expect((await read()).macs[0].status).toBe('wezterm-down')
  })

  it('a chat whose WezTerm did not answer is shown but not focusable', async () => {
    const read = createChatsReader({ listLocal: local({ wezterm: true, chats: [chat({ unknown: true })] }), peers: () => [] })
    expect((await read()).macs[0].chats[0]).toMatchObject({ canFocus: false, canSend: false, state: 'unknown' })
  })

  it('a lister that fails is an error state, not a crash or an empty list', async () => {
    const read = createChatsReader({ listLocal: async () => { throw new Error('python missing') }, peers: () => [] })
    expect((await read()).macs[0]).toMatchObject({ here: true, status: 'error' })
  })

  it('parses the CLI answer and refuses garbage', () => {
    expect(parseLocal('{"wezterm": true, "chats": []}')).toEqual({ wezterm: true, chats: [] })
    expect(() => parseLocal('not json')).toThrow()
    expect(() => parseLocal('{"chats": "x"}')).toThrow()
    expect(parseLocal('noise from a hook\n{"wezterm": false, "chats": []}')).toEqual({ wezterm: false, chats: [] })
  })

  it('drops malformed rows and never passes the socket or tty to the renderer', async () => {
    const read = createChatsReader({ listLocal: local({ wezterm: true, chats: [chat(), 'junk', { pane: 'x' }, chat({ pane: -1 })] }), peers: () => [] })
    const rows = (await read()).macs[0].chats
    expect(rows.map((c) => c.pane)).toEqual([16])
    expect(rows[0].socket).toBeUndefined()
    expect(rows[0].tty).toBeUndefined()
  })
})

describe('the other Mac', () => {
  it('its chats are listed read-only', async () => {
    const read = createChatsReader({
      listLocal: local({ wezterm: true, chats: [] }),
      peers: () => [{ id: 'mac-mini-1', host: 'gils-mac-mini' }],
      fetchRemote: async () => ({ wezterm: true, chats: [chat({ mac: 'mac-mini-1', pane: 3 })] })
    })
    const mini = (await read()).macs.find((m) => m.id === 'mac-mini-1')
    expect(mini).toMatchObject({ here: false, status: 'ok' })
    expect(mini.chats[0]).toMatchObject({ pane: 3, canFocus: false, canSend: false })
  })

  it('an unreachable Mac is a state', async () => {
    const read = createChatsReader({ listLocal: local({ wezterm: true, chats: [] }), peers: () => [{ id: 'mini', host: 'm' }], fetchRemote: async () => null })
    expect((await read()).macs.find((m) => m.id === 'mini').status).toBe('unreachable')
  })

  it('its answer is cached briefly so the dashboard never hammers it', async () => {
    let calls = 0
    let now = 0
    const read = createChatsReader({ listLocal: local({ wezterm: true, chats: [] }), peers: () => [{ id: 'mini', host: 'm' }],
      fetchRemote: async () => { calls++; return { wezterm: true, chats: [] } }, clock: () => now })
    await read(); await read()
    now += 60_000
    await read()
    expect(calls).toBe(2)
  })

  it('oversized titles and odd states from the other Mac are cut down to size', async () => {
    const read = createChatsReader({ listLocal: local({ wezterm: true, chats: [] }), peers: () => [{ id: 'mini', host: 'm' }],
      fetchRemote: async () => ({ wezterm: true, chats: [chat({ title: 'x'.repeat(5000), state: '<script>' })] }) })
    const c = (await read()).macs.find((m) => m.id === 'mini').chats[0]
    expect(c.title.length).toBeLessThanOrEqual(120)
    expect(c.state).toBe('unknown')
  })
})

describe('fetchChatsFrom (the real HTTP read)', () => {
  const serve = (handler) => new Promise((resolve) => {
    const server = http.createServer(handler).listen(0, '127.0.0.1', () => resolve(server))
  })

  it('reads a peer that answers', async () => {
    const s = await serve((req, res) => res.end(JSON.stringify({ wezterm: true, chats: [chat()] })))
    const got = await fetchChatsFrom('127.0.0.1', { port: s.address().port })
    s.close()
    expect(got.chats).toHaveLength(1)
  })

  it('a peer that hangs times out to null', async () => {
    const s = await serve(() => {})
    const got = await fetchChatsFrom('127.0.0.1', { port: s.address().port, timeoutMs: 200 })
    s.close()
    expect(got).toBeNull()
  })

  it('a peer that answers garbage or an error is null', async () => {
    const bad = await serve((req, res) => res.end('nope'))
    const err = await serve((req, res) => { res.statusCode = 500; res.end('{}') })
    expect(await fetchChatsFrom('127.0.0.1', { port: bad.address().port })).toBeNull()
    expect(await fetchChatsFrom('127.0.0.1', { port: err.address().port })).toBeNull()
    bad.close(); err.close()
  })
})

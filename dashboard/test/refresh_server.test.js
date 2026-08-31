import { describe, it, expect, vi, afterEach } from 'vitest'
import { createRefreshServer } from '../electron/main/refresh_server.js'

let server

afterEach(() => {
  server?.close()
  server = null
})

function listen(srv) {
  return new Promise((resolve) => {
    srv.listen(0, '127.0.0.1', () => resolve(srv.address().port))
  })
}

describe('createRefreshServer', () => {
  it('calls onRefresh for a POST /refresh and responds ok', async () => {
    const onRefresh = vi.fn()
    server = createRefreshServer(onRefresh)
    const port = await listen(server)

    const response = await fetch(`http://127.0.0.1:${port}/refresh`, { method: 'POST' })

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ ok: true })
    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('responds 404 and does not call onRefresh for any other route', async () => {
    const onRefresh = vi.fn()
    server = createRefreshServer(onRefresh)
    const port = await listen(server)

    const response = await fetch(`http://127.0.0.1:${port}/other`, { method: 'POST' })

    expect(response.status).toBe(404)
    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('responds 404 and does not call onRefresh for a GET on /refresh', async () => {
    const onRefresh = vi.fn()
    server = createRefreshServer(onRefresh)
    const port = await listen(server)

    const response = await fetch(`http://127.0.0.1:${port}/refresh`, { method: 'GET' })

    expect(response.status).toBe(404)
    expect(onRefresh).not.toHaveBeenCalled()
  })
})

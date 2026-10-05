import { describe, it, expect, vi } from 'vitest'
import { withCors, installDevSiteCors, DEV_SITE_PATTERN } from '../electron/main/dev_site_cors.js'

describe('dev site CORS for previews', () => {
  it('adds the allow-origin header and replaces any existing one regardless of case', () => {
    expect(withCors({ 'Content-Type': ['font/woff2'] })).toEqual({ 'Content-Type': ['font/woff2'], 'Access-Control-Allow-Origin': ['*'], 'Cache-Control': ['no-store'] })
    expect(withCors({ 'access-control-allow-origin': ['https://x'] })).toEqual({ 'Access-Control-Allow-Origin': ['*'], 'Cache-Control': ['no-store'] })
  })
  it('stops the app caching dev-site responses, so an edited stylesheet shows in previews immediately', () => {
    const out = withCors({ 'Cache-Control': ['max-age=31536000'], Expires: ['x'], ETag: ['"a"'], 'Last-Modified': ['y'], 'Content-Type': ['text/css'] })
    expect(out).toEqual({ 'Content-Type': ['text/css'], 'Access-Control-Allow-Origin': ['*'], 'Cache-Control': ['no-store'] })
  })
  it('only ever applies to the local dev site', () => {
    const onHeadersReceived = vi.fn()
    installDevSiteCors({ webRequest: { onHeadersReceived } })
    expect(onHeadersReceived.mock.calls[0][0]).toEqual({ urls: [DEV_SITE_PATTERN] })
    expect(DEV_SITE_PATTERN).toBe('http://localhost:8080/*')
    const cb = vi.fn()
    onHeadersReceived.mock.calls[0][1]({ responseHeaders: { A: ['b'] } }, cb)
    expect(cb).toHaveBeenCalledWith({ responseHeaders: { A: ['b'], 'Access-Control-Allow-Origin': ['*'], 'Cache-Control': ['no-store'] } })
  })
})

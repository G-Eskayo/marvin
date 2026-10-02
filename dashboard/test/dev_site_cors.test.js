import { describe, it, expect, vi } from 'vitest'
import { withCors, installDevSiteCors, DEV_SITE_PATTERN } from '../electron/main/dev_site_cors.js'

describe('dev site CORS for previews', () => {
  it('adds the allow-origin header and replaces any existing one regardless of case', () => {
    expect(withCors({ 'Content-Type': ['font/woff2'] })).toEqual({ 'Content-Type': ['font/woff2'], 'Access-Control-Allow-Origin': ['*'] })
    expect(withCors({ 'access-control-allow-origin': ['https://x'] })).toEqual({ 'Access-Control-Allow-Origin': ['*'] })
  })
  it('only ever applies to the local dev site', () => {
    const onHeadersReceived = vi.fn()
    installDevSiteCors({ webRequest: { onHeadersReceived } })
    expect(onHeadersReceived.mock.calls[0][0]).toEqual({ urls: [DEV_SITE_PATTERN] })
    expect(DEV_SITE_PATTERN).toBe('http://localhost:8080/*')
    const cb = vi.fn()
    onHeadersReceived.mock.calls[0][1]({ responseHeaders: { A: ['b'] } }, cb)
    expect(cb).toHaveBeenCalledWith({ responseHeaders: { A: ['b'], 'Access-Control-Allow-Origin': ['*'] } })
  })
})

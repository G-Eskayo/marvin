import { describe, it, expect } from 'vitest'
import { cleanIpcError } from '../src/lib/ipcError.js'

// Electron wraps an error thrown in a main-process handler as
// "Error invoking remote method 'mr:approve': Error: <real message>". Gil should see the
// real message, not the plumbing.
describe('cleanIpcError', () => {
  it('strips the Electron IPC wrapper and the redundant Error: prefix', () => {
    const e = new Error("Error invoking remote method 'mr:approve': Error: GH_AUTH_INVALID at merging: Bad credentials")
    expect(cleanIpcError(e)).toBe('GH_AUTH_INVALID at merging: Bad credentials')
  })
  it('leaves an ordinary message alone', () => {
    expect(cleanIpcError(new Error('something'))).toBe('something')
  })
  it('accepts a plain string', () => {
    expect(cleanIpcError("Error invoking remote method 'x': Error: y")).toBe('y')
  })
})

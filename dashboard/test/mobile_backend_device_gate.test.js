import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { whois, loadAllowlist, isAllowed } from '../mobile-backend/device_gate.js'

function withTempFile(content, fn) {
  const dir = mkdtempSync(path.join(tmpdir(), 'device-gate-test-'))
  const filePath = path.join(dir, 'allowlist.json')
  if (content !== undefined) writeFileSync(filePath, content)
  try {
    return fn(filePath)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe('device gate', () => {
  describe('loadAllowlist', () => {
    it('returns empty array when file does not exist', () => {
      withTempFile(undefined, (filePath) => {
        expect(loadAllowlist(filePath)).toEqual([])
      })
    })

    it('returns the devices array from valid JSON', () => {
      withTempFile(JSON.stringify({ devices: ['gils-iphone', 'gils-ipad'] }), (filePath) => {
        expect(loadAllowlist(filePath)).toEqual(['gils-iphone', 'gils-ipad'])
      })
    })

    it('returns empty array when file is malformed JSON', () => {
      withTempFile('not json', (filePath) => {
        expect(loadAllowlist(filePath)).toEqual([])
      })
    })

    it('returns empty array when devices key is missing', () => {
      withTempFile(JSON.stringify({ other: 'value' }), (filePath) => {
        expect(loadAllowlist(filePath)).toEqual([])
      })
    })
  })

  describe('isAllowed', () => {
    it('returns false when peer is null', () => {
      expect(isAllowed(null, ['gils-iphone'])).toBe(false)
    })

    it('returns false when peer is empty string', () => {
      expect(isAllowed('', ['gils-iphone'])).toBe(false)
    })

    it('returns true when peer is in allowlist', () => {
      expect(isAllowed('gils-iphone', ['gils-iphone', 'gils-ipad'])).toBe(true)
    })

    it('returns false when peer is not in allowlist', () => {
      expect(isAllowed('unknown-device', ['gils-iphone', 'gils-ipad'])).toBe(false)
    })

    it('matches case-insensitively', () => {
      expect(isAllowed('GILS-IPHONE', ['gils-iphone'])).toBe(true)
      expect(isAllowed('Gils-iPhone', ['GILS-IPHONE'])).toBe(true)
      expect(isAllowed('gILS-iPHONE', ['gils-iphone'])).toBe(true)
    })

    it('returns false when allowlist is empty', () => {
      expect(isAllowed('gils-iphone', [])).toBe(false)
    })
  })

  describe('whois', () => {
    it('returns peer name on successful lookup', async () => {
      const fakeExecFn = async () => ({
        stdout: JSON.stringify({
          Node: { Name: 'gils-iphone.tailnet-abc.ts.net', Hostnames: [] }
        })
      })
      const result = await whois('100.1.2.3', fakeExecFn)
      expect(result).toBe('gils-iphone')
    })

    it('returns first label of hostname', async () => {
      const fakeExecFn = async () => ({
        stdout: JSON.stringify({
          Node: { Name: 'my-long-device-name.tailnet-abc.ts.net' }
        })
      })
      const result = await whois('100.1.2.3', fakeExecFn)
      expect(result).toBe('my-long-device-name')
    })

    it('falls back to first Hostnames entry if Name is empty', async () => {
      const fakeExecFn = async () => ({
        stdout: JSON.stringify({
          Node: { Name: '', Hostnames: ['fallback-device.tailnet-abc.ts.net'] }
        })
      })
      const result = await whois('100.1.2.3', fakeExecFn)
      expect(result).toBe('fallback-device')
    })

    it('returns null on missing Node', async () => {
      const fakeExecFn = async () => ({
        stdout: JSON.stringify({})
      })
      const result = await whois('100.1.2.3', fakeExecFn)
      expect(result).toBeNull()
    })

    it('returns null on empty Node.Name and Hostnames', async () => {
      const fakeExecFn = async () => ({
        stdout: JSON.stringify({
          Node: { Name: '', Hostnames: [] }
        })
      })
      const result = await whois('100.1.2.3', fakeExecFn)
      expect(result).toBeNull()
    })

    it('returns null when execFn throws', async () => {
      const fakeExecFn = async () => {
        throw new Error('Tailscale not running')
      }
      const result = await whois('100.1.2.3', fakeExecFn)
      expect(result).toBeNull()
    })

    it('returns null on invalid JSON in stdout', async () => {
      const fakeExecFn = async () => ({
        stdout: 'not json'
      })
      const result = await whois('100.1.2.3', fakeExecFn)
      expect(result).toBeNull()
    })
  })
})

import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { isMacOrigin } from '../webhook-server/safety_label_origin.js'
import { isRegisteredMacHostname } from '../electron/main/device_identity.js'

const registryFixture = {
  'mac-mini-1': { hardware_uuid: 'MAC-MINI-UUID', kind: 'desktop', tailscale_hostname: 'gils-mac-mini', os: 'macos' },
  'macbook-pro-1': { hardware_uuid: 'MACBOOK-UUID', kind: 'laptop', tailscale_hostname: 'some-macbook', os: 'macos' },
  kali: { hardware_uuid: 'KALI-UUID', kind: 'desktop', tailscale_hostname: 'kali-box', os: 'linux' }
}

async function withRegistry(devices, fn) {
  const dir = mkdtempSync(path.join(tmpdir(), 'safety-origin-'))
  const networkPath = path.join(dir, 'marvin-network.json')
  writeFileSync(networkPath, JSON.stringify({ devices }))
  try {
    return await fn(networkPath)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe('isMacOrigin', () => {
  it('returns true for loopback 127.0.0.1', async () => {
    const result = await isMacOrigin('127.0.0.1', { isMacHostname: () => true })
    expect(result).toBe(true)
  })

  it('returns true for loopback ::1', async () => {
    const result = await isMacOrigin('::1', { isMacHostname: () => true })
    expect(result).toBe(true)
  })

  it('returns false for IPv6-mapped loopback even without calling whois', async () => {
    let whoisCalled = false
    const fakeWhois = async () => {
      whoisCalled = true
      return 'some-hostname'
    }
    const result = await isMacOrigin('::ffff:127.0.0.1', { whoisFn: fakeWhois, isMacHostname: () => true })
    // Stripped of prefix, becomes 127.0.0.1, which is loopback
    expect(result).toBe(true)
    expect(whoisCalled).toBe(false)
  })

  it('returns false for non-Tailscale IP without calling whois', async () => {
    let whoisCalled = false
    const fakeWhois = async () => {
      whoisCalled = true
      return 'some-hostname'
    }
    const result = await isMacOrigin('192.168.1.100', { whoisFn: fakeWhois, isMacHostname: () => true })
    expect(result).toBe(false)
    expect(whoisCalled).toBe(false)
  })

  it('returns false when whois returns null', async () => {
    const fakeWhois = async () => null
    return withRegistry(registryFixture, async (networkPath) => {
      const result = await isMacOrigin('100.64.0.1', {
        whoisFn: fakeWhois,
        isMacHostname: (h) => isRegisteredMacHostname(h, networkPath)
      })
      expect(result).toBe(false)
    })
  })

  it('returns false when whois throws', async () => {
    const fakeWhois = async () => {
      throw new Error('Tailscale not running')
    }
    return withRegistry(registryFixture, async (networkPath) => {
      const result = await isMacOrigin('100.64.0.1', {
        whoisFn: fakeWhois,
        isMacHostname: (h) => isRegisteredMacHostname(h, networkPath)
      })
      expect(result).toBe(false)
    })
  })

  it('returns true for Tailscale address resolving to a registered Mac', async () => {
    return withRegistry(registryFixture, async (networkPath) => {
      const fakeWhois = async () => 'gils-mac-mini'
      const result = await isMacOrigin('100.64.0.1', {
        whoisFn: fakeWhois,
        isMacHostname: (h) => isRegisteredMacHostname(h, networkPath)
      })
      expect(result).toBe(true)
    })
  })

  it('returns false for Tailscale address resolving to a non-Mac', async () => {
    return withRegistry(registryFixture, async (networkPath) => {
      const fakeWhois = async () => 'kali-box'
      const result = await isMacOrigin('100.64.0.1', {
        whoisFn: fakeWhois,
        isMacHostname: (h) => isRegisteredMacHostname(h, networkPath)
      })
      expect(result).toBe(false)
    })
  })

  it('returns false for Tailscale address resolving to an unregistered hostname', async () => {
    return withRegistry(registryFixture, async (networkPath) => {
      const fakeWhois = async () => 'unknown-mac'
      const result = await isMacOrigin('100.64.0.1', {
        whoisFn: fakeWhois,
        isMacHostname: (h) => isRegisteredMacHostname(h, networkPath)
      })
      expect(result).toBe(false)
    })
  })

  it('matches hostnames case-insensitively', async () => {
    return withRegistry(registryFixture, async (networkPath) => {
      const fakeWhois = async () => 'GILS-MAC-MINI'
      const result = await isMacOrigin('100.64.0.1', {
        whoisFn: fakeWhois,
        isMacHostname: (h) => isRegisteredMacHostname(h, networkPath)
      })
      expect(result).toBe(true)
    })
  })

  it('accepts valid Tailscale IPv6 addresses', async () => {
    return withRegistry(registryFixture, async (networkPath) => {
      const fakeWhois = async () => 'some-macbook'
      const result = await isMacOrigin('fd7a:115c:a1e0::1', {
        whoisFn: fakeWhois,
        isMacHostname: (h) => isRegisteredMacHostname(h, networkPath)
      })
      expect(result).toBe(true)
    })
  })

  it('rejects invalid or missing remote addresses', async () => {
    return withRegistry(registryFixture, async (networkPath) => {
      const fakeWhois = async () => 'gils-mac-mini'
      expect(await isMacOrigin(null, { whoisFn: fakeWhois, isMacHostname: (h) => isRegisteredMacHostname(h, networkPath) })).toBe(false)
      expect(await isMacOrigin(undefined, { whoisFn: fakeWhois, isMacHostname: (h) => isRegisteredMacHostname(h, networkPath) })).toBe(false)
    })
  })
})

describe('isRegisteredMacHostname', () => {
  it('returns true for a registered Mac', async () => {
    return withRegistry(registryFixture, (networkPath) => {
      expect(isRegisteredMacHostname('gils-mac-mini', networkPath)).toBe(true)
    })
  })

  it('returns false for a registered non-Mac (Linux)', async () => {
    return withRegistry(registryFixture, (networkPath) => {
      expect(isRegisteredMacHostname('kali-box', networkPath)).toBe(false)
    })
  })

  it('returns false for an unregistered hostname', async () => {
    return withRegistry(registryFixture, (networkPath) => {
      expect(isRegisteredMacHostname('unknown-mac', networkPath)).toBe(false)
    })
  })

  it('matches hostnames case-insensitively', async () => {
    return withRegistry(registryFixture, (networkPath) => {
      expect(isRegisteredMacHostname('GILS-MAC-MINI', networkPath)).toBe(true)
      expect(isRegisteredMacHostname('Gils-Mac-Mini', networkPath)).toBe(true)
    })
  })

  it('returns false for null or empty hostname', async () => {
    return withRegistry(registryFixture, (networkPath) => {
      expect(isRegisteredMacHostname(null, networkPath)).toBe(false)
      expect(isRegisteredMacHostname('', networkPath)).toBe(false)
      expect(isRegisteredMacHostname(undefined, networkPath)).toBe(false)
    })
  })

  it('defaults to macOS when os field is missing', async () => {
    const registry = {
      'mac-default': { hardware_uuid: 'UUID', tailscale_hostname: 'mac-default' } // No os field
    }
    return withRegistry(registry, (networkPath) => {
      expect(isRegisteredMacHostname('mac-default', networkPath)).toBe(true)
    })
  })

  it('returns false when registry file is missing', () => {
    const result = isRegisteredMacHostname('gils-mac-mini', '/nonexistent/marvin-network.json')
    expect(result).toBe(false)
  })
})

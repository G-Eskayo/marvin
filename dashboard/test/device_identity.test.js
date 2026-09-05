import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import { homedir } from 'os'
import path from 'path'
import {
  resolveDeviceId,
  primaryHostTailscaleName,
  isPrimaryHost,
  resolveServiceDefaults
} from '../electron/main/device_identity.js'

const registryFixture = {
  'mac-mini-1': { hardware_uuid: 'MAC-MINI-UUID', kind: 'desktop', tailscale_hostname: 'gils-mac-mini' },
  'macbook-pro-1': { hardware_uuid: 'MACBOOK-UUID', kind: 'laptop', tailscale_hostname: 'some-macbook' }
}

function withRegistry(devices, fn) {
  const dir = mkdtempSync(path.join(tmpdir(), 'device-identity-'))
  const networkPath = path.join(dir, 'marvin-network.json')
  writeFileSync(networkPath, JSON.stringify({ devices }))
  try {
    return fn(networkPath)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe('resolveDeviceId', () => {
  it('matches by hardware UUID, not label', () => {
    withRegistry(registryFixture, (networkPath) => {
      expect(resolveDeviceId(() => 'MACBOOK-UUID', networkPath)).toBe('macbook-pro-1')
    })
  })

  it('returns null when this machine is not in the registry', () => {
    withRegistry(registryFixture, (networkPath) => {
      expect(resolveDeviceId(() => 'UNKNOWN-UUID', networkPath)).toBeNull()
    })
  })

  it('returns null when the registry file does not exist', () => {
    expect(resolveDeviceId(() => 'MAC-MINI-UUID', path.join(homedir(), 'nonexistent-marvin-network.json'))).toBeNull()
  })
})

describe('primaryHostTailscaleName', () => {
  it("resolves the registry's desktop-kind device hostname", () => {
    withRegistry(registryFixture, (networkPath) => {
      expect(primaryHostTailscaleName(networkPath)).toBe('gils-mac-mini')
    })
  })

  it('returns null when no desktop-kind device is registered', () => {
    withRegistry({ 'laptop-1': registryFixture['macbook-pro-1'] }, (networkPath) => {
      expect(primaryHostTailscaleName(networkPath)).toBeNull()
    })
  })
})

describe('isPrimaryHost', () => {
  it('is true when this machine is the desktop-kind device', () => {
    withRegistry(registryFixture, (networkPath) => {
      expect(isPrimaryHost(() => 'MAC-MINI-UUID', networkPath)).toBe(true)
    })
  })

  it('is false for any other registered device', () => {
    withRegistry(registryFixture, (networkPath) => {
      expect(isPrimaryHost(() => 'MACBOOK-UUID', networkPath)).toBe(false)
    })
  })

  it('is false when this machine is not registered at all', () => {
    withRegistry(registryFixture, (networkPath) => {
      expect(isPrimaryHost(() => 'UNKNOWN-UUID', networkPath)).toBe(false)
    })
  })
})

describe('resolveServiceDefaults', () => {
  it('defaults to localhost on the primary host', () => {
    withRegistry(registryFixture, (networkPath) => {
      expect(resolveServiceDefaults(() => 'MAC-MINI-UUID', networkPath)).toEqual({ host: 'localhost' })
    })
  })

  it("defaults to the primary host's tailscale hostname on any other registered device", () => {
    withRegistry(registryFixture, (networkPath) => {
      expect(resolveServiceDefaults(() => 'MACBOOK-UUID', networkPath)).toEqual({ host: 'gils-mac-mini' })
    })
  })

  it('falls back to localhost when the primary host itself is unresolvable', () => {
    withRegistry({ 'macbook-pro-1': registryFixture['macbook-pro-1'] }, (networkPath) => {
      expect(resolveServiceDefaults(() => 'MACBOOK-UUID', networkPath)).toEqual({ host: 'localhost' })
    })
  })
})

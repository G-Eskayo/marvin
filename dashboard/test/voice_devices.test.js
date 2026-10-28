import { describe, it, expect } from 'vitest'
import { DEVICE_ABILITIES, isKnownDevice } from '../mobile-backend/voice_devices.js'

describe('voice_devices', () => {
  describe('DEVICE_ABILITIES', () => {
    it('defines abilities for all known devices', () => {
      expect(DEVICE_ABILITIES).toHaveProperty('homepod')
      expect(DEVICE_ABILITIES).toHaveProperty('mac')
      expect(DEVICE_ABILITIES).toHaveProperty('iphone')
      expect(DEVICE_ABILITIES).toHaveProperty('watch')
    })

    it('each device has required properties', () => {
      for (const [key, device] of Object.entries(DEVICE_ABILITIES)) {
        expect(device).toHaveProperty('name')
        expect(device).toHaveProperty('capabilities')
        expect(device).toHaveProperty('minVersion')
        expect(Array.isArray(device.capabilities)).toBe(true)
      }
    })
  })

  describe('isKnownDevice', () => {
    it('test 2: recognizes known devices', () => {
      expect(isKnownDevice('homepod')).toBe(true)
      expect(isKnownDevice('mac')).toBe(true)
      expect(isKnownDevice('iphone')).toBe(true)
      expect(isKnownDevice('watch')).toBe(true)
    })

    it('handles case-insensitivity', () => {
      expect(isKnownDevice('HOMEPOD')).toBe(true)
      expect(isKnownDevice('HomePod')).toBe(true)
      expect(isKnownDevice('iPhone')).toBe(true)
    })

    it('rejects unknown devices', () => {
      expect(isKnownDevice('android')).toBe(false)
      expect(isKnownDevice('alexa')).toBe(false)
    })

    it('rejects invalid input', () => {
      expect(isKnownDevice(null)).toBe(false)
      expect(isKnownDevice(undefined)).toBe(false)
      expect(isKnownDevice(123)).toBe(false)
      expect(isKnownDevice('')).toBe(false)
    })
  })
})

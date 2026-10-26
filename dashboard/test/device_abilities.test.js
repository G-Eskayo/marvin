import { describe, it, expect } from 'vitest'
import { getAbilities, isKnownDevice } from '../mobile-backend/device_abilities.js'

describe('device_abilities', () => {
  describe('getAbilities()', () => {
    it('returns abilities for homepod', () => {
      const abilities = getAbilities('homepod')
      expect(abilities).toContain('listen')
      expect(abilities).toContain('speak')
    })

    it('returns abilities for mac', () => {
      const abilities = getAbilities('mac')
      expect(abilities).toContain('show')
      expect(abilities).toContain('touch')
      expect(abilities).toContain('listen')
      expect(abilities).toContain('speak')
    })

    it('returns abilities for iphone', () => {
      const abilities = getAbilities('iphone')
      expect(abilities).toContain('show')
      expect(abilities).toContain('touch')
      expect(abilities).toContain('listen')
      expect(abilities).toContain('speak')
    })

    it('returns abilities for watch', () => {
      const abilities = getAbilities('watch')
      expect(abilities).toContain('show')
      expect(abilities).toContain('listen')
      expect(abilities).toContain('speak')
    })

    it('returns empty array for unknown device', () => {
      const abilities = getAbilities('unknown')
      expect(abilities).toEqual([])
    })

    it('is case-insensitive', () => {
      const lowerAbilities = getAbilities('iphone')
      const upperAbilities = getAbilities('IPHONE')
      const mixedAbilities = getAbilities('IPhone')
      expect(lowerAbilities).toEqual(upperAbilities)
      expect(lowerAbilities).toEqual(mixedAbilities)
    })
  })

  describe('isKnownDevice()', () => {
    it('returns true for known devices', () => {
      expect(isKnownDevice('homepod')).toBe(true)
      expect(isKnownDevice('mac')).toBe(true)
      expect(isKnownDevice('iphone')).toBe(true)
      expect(isKnownDevice('watch')).toBe(true)
    })

    it('returns false for unknown devices', () => {
      expect(isKnownDevice('unknown')).toBe(false)
      expect(isKnownDevice('android')).toBe(false)
      expect(isKnownDevice('')).toBe(false)
    })

    it('is case-insensitive', () => {
      expect(isKnownDevice('IPHONE')).toBe(true)
      expect(isKnownDevice('IPhone')).toBe(true)
      expect(isKnownDevice('MAC')).toBe(true)
    })

    it('returns false for null or undefined', () => {
      expect(isKnownDevice(null)).toBe(false)
      expect(isKnownDevice(undefined)).toBe(false)
    })
  })
})

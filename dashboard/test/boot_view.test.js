import { describe, it, expect } from 'vitest'
import { shouldPlay, bannerTone, lineTone, lineTarget, bannerTarget, healthFocus } from '../src/lib/boot_view.js'

describe('shouldPlay', () => {
  it('plays only on the launch\'s first load, without Reduce Motion, where animation works', () => {
    expect(shouldPlay({ show: true, reducedMotion: false, canAnimate: true })).toBe(true)
    expect(shouldPlay({ show: false, reducedMotion: false, canAnimate: true })).toBe(false)
    expect(shouldPlay({ show: true, reducedMotion: true, canAnimate: true })).toBe(false)
    expect(shouldPlay({ show: true, reducedMotion: false, canAnimate: false })).toBe(false)
    expect(shouldPlay({})).toBe(false)
  })
})

describe('bannerTone', () => {
  it('looks nominal only when the verdict really is nominal', () => {
    expect(bannerTone({ nominal: true, tone: 'nominal' })).toBe('nominal')
    expect(bannerTone({ nominal: false, tone: 'nominal' })).toBe('unknown')
    expect(bannerTone({ nominal: true, tone: 'issues' })).toBe('issues')
    expect(bannerTone({ nominal: false, tone: 'issues' })).toBe('issues')
    expect(bannerTone({ tone: 'something-new' })).toBe('unknown')
    expect(bannerTone(undefined)).toBe('unknown')
  })
})

describe('lineTone', () => {
  it('never turns an unexpected level green', () => {
    expect(lineTone('green')).toBe('green')
    expect(lineTone('red')).toBe('red')
    expect(lineTone('lock')).toBe('lock')
    expect(lineTone('grey')).toBe('yellow')
    expect(lineTone(undefined)).toBe('yellow')
  })
})

describe('what is clickable in the boot (#433)', () => {
  it('a line is clickable only with a real tab target', () => {
    expect(lineTarget({ target: { tab: 'health', check: 'main:green' } })).toEqual({ tab: 'health', check: 'main:green' })
    expect(lineTarget({ target: { tab: 'health' } })).toEqual({ tab: 'health' })
    expect(lineTarget({ target: null })).toBeNull()
    expect(lineTarget({})).toBeNull()
    expect(lineTarget({ target: { tab: 'nowhere' } })).toBeNull()
    expect(lineTarget({ target: { tab: 'health', check: 42 } })).toEqual({ tab: 'health' })
  })
  it('the banner is clickable only when it is not nominal', () => {
    expect(bannerTarget({ nominal: true, tone: 'nominal' })).toBeNull()
    expect(bannerTarget({ nominal: false, tone: 'issues' })).toEqual({ tab: 'health' })
    expect(bannerTarget({ nominal: false, tone: 'unknown' })).toEqual({ tab: 'health' })
  })
})

describe('healthFocus: which check the Health tab should land on', () => {
  it('only a health nav with a string check id focuses a check', () => {
    expect(healthFocus({ tab: 'health', check: 'disk:space@mac-mini-1', at: 1 })).toBe('disk:space@mac-mini-1')
    expect(healthFocus({ tab: 'health', at: 1 })).toBeNull()
    expect(healthFocus({ tab: 'docs', check: 'x', at: 1 })).toBeNull()
    expect(healthFocus({ tab: 'health', check: { evil: 1 } })).toBeNull()
    expect(healthFocus({ tab: 'health', check: '' })).toBeNull()
    expect(healthFocus(null)).toBeNull()
  })
})

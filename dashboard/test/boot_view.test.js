import { describe, it, expect } from 'vitest'
import { shouldPlay, bannerTone, lineTone } from '../src/lib/boot_view.js'

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

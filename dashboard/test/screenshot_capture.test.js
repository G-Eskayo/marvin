import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { selectContentPage, captureLaunchEnv } from '../src/lib/screenshot_capture.js'

describe('captureLaunchEnv', () => {
  it('gives the capture copy an ephemeral refresh port and marks it as evidence capture', () => {
    const env = captureLaunchEnv({ PATH: '/usr/bin', HOME: '/Users/x' })
    expect(env.MARVIN_DASHBOARD_REFRESH_PORT).toBe('0')
    expect(env.MARVIN_EVIDENCE_CAPTURE).toBe('1')
    expect(env.PATH).toBe('/usr/bin')
    expect(env.HOME).toBe('/Users/x')
  })

  it('overrides an inherited refresh port so the copy can never take the real one', () => {
    const env = captureLaunchEnv({ MARVIN_DASHBOARD_REFRESH_PORT: '7879', MARVIN_EVIDENCE_CAPTURE: '0' })
    expect(env.MARVIN_DASHBOARD_REFRESH_PORT).toBe('0')
    expect(env.MARVIN_EVIDENCE_CAPTURE).toBe('1')
  })

  it('does not mutate the env it was given', () => {
    const base = { MARVIN_DASHBOARD_REFRESH_PORT: '7879' }
    captureLaunchEnv(base)
    expect(base).toEqual({ MARVIN_DASHBOARD_REFRESH_PORT: '7879' })
  })

  it('drops undefined values (child_process env must be strings)', () => {
    const env = captureLaunchEnv({ A: 'a', B: undefined })
    expect('B' in env).toBe(false)
  })

  it('is what capture_screenshot.mjs actually passes to the launched app', () => {
    const src = readFileSync(path.resolve(import.meta.dirname, '../scripts/capture_screenshot.mjs'), 'utf8')
    expect(src).toMatch(/import \{[^}]*captureLaunchEnv[^}]*\} from '\.\.\/src\/lib\/screenshot_capture\.js'/)
    expect(src).toMatch(/chromium\.launch\(\{[\s\S]*env:\s*captureLaunchEnv\(process\.env\)[\s\S]*\}\)/)
  })
})

describe('selectContentPage', () => {
  it('returns the first non-devtools page', () => {
    const pages = [
      { url: () => 'devtools://whatever' },
      { url: () => 'http://localhost:5173/' },
      { url: () => 'http://localhost:5173/other' },
    ]
    expect(selectContentPage(pages)).toBe(pages[1])
  })

  it('skips devtools:// pages', () => {
    const pages = [
      { url: () => 'devtools://one' },
      { url: () => 'devtools://two' },
      { url: () => 'about:blank' },
    ]
    expect(selectContentPage(pages)).toBe(pages[2])
  })

  it('returns null when there are no pages', () => {
    expect(selectContentPage([])).toBe(null)
  })

  it('returns null when all pages are devtools', () => {
    const pages = [
      { url: () => 'devtools://one' },
      { url: () => 'devtools://two' },
    ]
    expect(selectContentPage(pages)).toBe(null)
  })

  it('handles pages with missing or falsy url methods', () => {
    const pages = [
      { url: () => '' },
      { url: () => 'http://localhost:5173/' },
    ]
    expect(selectContentPage(pages)).toBe(pages[1])
  })
})

// Where a new `marvin show` window opens (#715, owner's answer on PR #1029): the size and place of the last show
// window Gil moved. Real files in a throwaway folder; screens as plain work-area rectangles.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, readFileSync, readdirSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { pickShowBounds, createBoundsStore, DEFAULT_SHOW_SIZE, validBounds } from '../electron/main/show_bounds.js'

const LAPTOP = { x: 0, y: 25, width: 1512, height: 920 }
const EXTERNAL = { x: 1512, y: 0, width: 2560, height: 1415 }

describe('pickShowBounds', () => {
  it('nothing saved: the default size, centred', () => {
    expect(pickShowBounds(null, [LAPTOP])).toEqual(DEFAULT_SHOW_SIZE)
  })

  it('a saved place on a screen opens exactly there, at the saved size', () => {
    const saved = { x: 800, y: 60, width: 700, height: 840 }
    expect(pickShowBounds(saved, [LAPTOP])).toEqual(saved)
  })

  it('a place on the second screen is kept while that screen is plugged in', () => {
    const saved = { x: 3000, y: 100, width: 1000, height: 900 }
    expect(pickShowBounds(saved, [LAPTOP, EXTERNAL])).toEqual(saved)
  })

  it('a place on a screen that was unplugged falls back to the default, never off screen', () => {
    expect(pickShowBounds({ x: 3000, y: 100, width: 1000, height: 900 }, [LAPTOP])).toEqual(DEFAULT_SHOW_SIZE)
  })

  it('a window only grazing a screen (title bar off it) is not "on" it', () => {
    // 50px of the window over the laptop's right edge: too little to grab.
    expect(pickShowBounds({ x: 1462, y: 100, width: 800, height: 600 }, [LAPTOP])).toEqual(DEFAULT_SHOW_SIZE)
    // the title bar above the top of every screen
    expect(pickShowBounds({ x: 100, y: -500, width: 800, height: 480 }, [LAPTOP])).toEqual(DEFAULT_SHOW_SIZE)
  })

  it('a size saved on the big screen is cut down to fit the laptop it now lands on, and kept on it', () => {
    const b = pickShowBounds({ x: 1000, y: 30, width: 2400, height: 1400 }, [LAPTOP])
    expect(b.width).toBe(LAPTOP.width)
    expect(b.height).toBe(LAPTOP.height)
    expect(b.x).toBe(0)
    expect(b.y).toBe(25)
  })

  it('garbage is ignored: NaN, strings, too small, missing fields, no screens', () => {
    for (const bad of [{ x: NaN, y: 0, width: 900, height: 700 }, { x: '1', y: 0, width: 900, height: 700 }, { x: 0, y: 0, width: 10, height: 10 }, { x: 0, y: 0 }, 'x', 7]) {
      expect(pickShowBounds(bad, [LAPTOP])).toEqual(DEFAULT_SHOW_SIZE)
    }
    expect(pickShowBounds({ x: 10, y: 30, width: 900, height: 700 }, [])).toEqual(DEFAULT_SHOW_SIZE)
    expect(pickShowBounds({ x: 10, y: 30, width: 900, height: 700 }, [null, { x: 'a' }])).toEqual(DEFAULT_SHOW_SIZE)
  })
})

describe('createBoundsStore', () => {
  let dir
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'show-bounds-')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))

  it('saves and loads the last bounds, in a folder it makes, leaving no temp file behind', () => {
    const file = path.join(dir, 'nested', 'show-window-bounds.json')
    const s = createBoundsStore(file)
    expect(s.load()).toBeNull()
    expect(s.save({ x: 5, y: 40, width: 800, height: 600, extra: 'dropped' })).toBe(true)
    expect(JSON.parse(readFileSync(file, 'utf8'))).toEqual({ x: 5, y: 40, width: 800, height: 600 })
    expect(createBoundsStore(file).load()).toEqual({ x: 5, y: 40, width: 800, height: 600 })
    expect(readdirSync(path.dirname(file))).toEqual(['show-window-bounds.json'])
  })

  it('the latest move wins', () => {
    const s = createBoundsStore(path.join(dir, 'b.json'))
    s.save({ x: 5, y: 40, width: 800, height: 600 })
    s.save({ x: 300, y: 90, width: 1000, height: 700 })
    expect(s.load()).toEqual({ x: 300, y: 90, width: 1000, height: 700 })
  })

  it('a broken or hand-edited file reads as nothing saved; bad bounds are never written', () => {
    const file = path.join(dir, 'b.json')
    writeFileSync(file, '{not json')
    const s = createBoundsStore(file)
    expect(s.load()).toBeNull()
    writeFileSync(file, JSON.stringify({ x: 0, y: 0, width: 1, height: 1 }))
    expect(s.load()).toBeNull()
    expect(s.save({ x: 0, y: 0, width: 'big', height: 600 })).toBe(false)
    expect(readFileSync(file, 'utf8')).toContain('"width":1')
  })

  it('a folder that cannot be written is a quiet false, not a crash', () => {
    const blocker = path.join(dir, 'file')
    writeFileSync(blocker, 'x')
    expect(createBoundsStore(path.join(blocker, 'b.json')).save({ x: 0, y: 30, width: 800, height: 600 })).toBe(false)
    expect(validBounds({ x: 0, y: 30, width: 800, height: 600 })).toBe(true)
  })
})

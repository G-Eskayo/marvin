import { readFileSync, writeFileSync, mkdirSync, renameSync } from 'fs'
import path from 'path'

// Where a new `marvin show` window opens (G-Eskayo/marvin#715, owner's answer on PR #1029: "Same size and place as
// the last window I moved"). Every show window saves its bounds when Gil moves or resizes it; the next new window
// opens there. A saved place that is no longer on any screen (a display unplugged) falls back to the default size,
// centred, and a saved size bigger than the screen it lands on is cut down to fit.

export const DEFAULT_SHOW_SIZE = { width: 920, height: 760 }
export const MIN_SHOW_SIZE = { width: 420, height: 360 }
// How much of the window's top strip must be on a screen for it to count as reachable (it is where it is dragged).
const GRAB = { width: 100, height: 40 }

const num = (v) => typeof v === 'number' && Number.isFinite(v)

export function validBounds(b) {
  return !!b && num(b.x) && num(b.y) && num(b.width) && num(b.height) && b.width >= MIN_SHOW_SIZE.width && b.height >= MIN_SHOW_SIZE.height
}

// saved: { x, y, width, height } | null; areas: the screens' work areas. -> { x, y, width, height } | { width, height }
// (the second means "centred", the default).
export function pickShowBounds(saved, areas = []) {
  if (!validBounds(saved)) return { ...DEFAULT_SHOW_SIZE }
  for (const a of areas || []) {
    if (!a || !num(a.x) || !num(a.y) || !num(a.width) || !num(a.height)) continue
    // The top strip of the window, as dragged, overlaps this screen by at least GRAB.
    const left = Math.max(saved.x, a.x)
    const right = Math.min(saved.x + saved.width, a.x + a.width)
    const top = Math.max(saved.y, a.y)
    const bottom = Math.min(saved.y + GRAB.height, a.y + a.height)
    if (right - left < GRAB.width || bottom - top < Math.min(GRAB.height, 1)) continue
    const width = Math.max(MIN_SHOW_SIZE.width, Math.min(saved.width, a.width))
    const height = Math.max(MIN_SHOW_SIZE.height, Math.min(saved.height, a.height))
    // Kept on this screen once cut to size: the title bar never sits above the screen's top.
    const x = Math.min(Math.max(saved.x, a.x), a.x + a.width - width)
    const y = Math.min(Math.max(saved.y, a.y), a.y + a.height - height)
    return { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) }
  }
  return { ...DEFAULT_SHOW_SIZE }
}

// The saved bounds, one small JSON file in the app's data folder. A missing or broken file reads as nothing saved;
// a save is written whole (temp file, then rename) so a crash never leaves half a file.
export function createBoundsStore(file, fs = { readFileSync, writeFileSync, mkdirSync, renameSync }) {
  return {
    load() {
      try {
        const b = JSON.parse(fs.readFileSync(file, 'utf8'))
        return validBounds(b) ? { x: b.x, y: b.y, width: b.width, height: b.height } : null
      } catch {
        return null
      }
    },
    save(b) {
      if (!validBounds(b)) return false
      try {
        fs.mkdirSync(path.dirname(file), { recursive: true })
        const tmp = `${file}.${process.pid}.tmp`
        fs.writeFileSync(tmp, JSON.stringify({ x: b.x, y: b.y, width: b.width, height: b.height }))
        fs.renameSync(tmp, file)
        return true
      } catch {
        return false
      }
    }
  }
}

// The zoom maths behind the shared image viewer (G-Eskayo/marvin#402). Pure, so it is tested without a DOM.

export const MIN_SCALE = 0.05
export const MAX_SCALE = 8
const STEP = 1.25
// An image that fitting whole would shrink to a column narrower than this share of the window is a full-page
// screenshot: open it fit-to-width and let it scroll, instead of shrinking it to an unreadable column.
const COLUMN_SHARE = 0.4

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0)

export function clampScale(s) {
  if (typeof s !== 'number' || Number.isNaN(s)) return 1
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))
}

export function fitScale(natural, viewport) {
  const w = num(natural?.w)
  const h = num(natural?.h)
  const vw = num(viewport?.w)
  const vh = num(viewport?.h)
  if (w <= 0 || h <= 0 || vw <= 0 || vh <= 0) return 1
  const byWidth = vw / w
  const whole = Math.min(byWidth, vh / h)
  const tall = w * whole < vw * COLUMN_SHARE && h > vh
  return clampScale(Math.min(1, tall ? byWidth : whole))
}

export const stepScale = (s, dir) => clampScale(dir > 0 ? s * STEP : s / STEP)

// Double-click: Fit ↔ 100%. When the fit already is 100% (a small image), go to 200% so it always zooms.
export function toggleScale(scale, fit) {
  const atFit = Math.abs(scale - fit) < 0.001
  if (!atFit) return fit
  return Math.abs(fit - 1) < 0.001 ? 2 : 1
}

// One axis: the new scroll offset so the image pixel under `point` (relative to the viewport) stays under it after
// zooming from `from` to `to`. A smaller-than-viewport image is centred, so its offset is part of the sum.
export function zoomScroll({ scroll, point, client, natural, from, to } = {}) {
  const s1 = num(from) || 1
  const s2 = num(to) || 1
  const c = num(client)
  const n = num(natural)
  const p = num(point)
  const off1 = Math.max(0, (c - n * s1) / 2)
  const off2 = Math.max(0, (c - n * s2) / 2)
  const imagePx = (num(scroll) + p - off1) / s1
  const maxScroll = Math.max(0, n * s2 - c)
  return Math.min(maxScroll, Math.max(0, imagePx * s2 + off2 - p))
}

// A trackpad pinch arrives as a wheel event with ctrlKey; ⌘-scroll has metaKey. Plain scrolling just scrolls.
export function wheelZoomFactor(e) {
  if (!e?.ctrlKey && !e?.metaKey) return null
  const d = Math.max(-25, Math.min(25, num(e.deltaY)))   // one mouse-wheel notch ≈ one + step; a pinch is finer
  return Math.exp(-d * 0.01)
}

export function viewerKey(e) {
  const key = e?.key
  if (key === 'Escape') return 'close'
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e?.target?.tagName || '')) return null
  if (key === 'ArrowRight') return 'next'
  if (key === 'ArrowLeft') return 'prev'
  if (key === '+' || key === '=') return 'in'
  if (key === '-' || key === '_') return 'out'
  if (key === '0') return 'fit'
  return null
}

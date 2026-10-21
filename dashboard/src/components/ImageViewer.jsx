import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { fitScale, stepScale, toggleScale, zoomScroll, wheelZoomFactor, viewerKey, clampScale } from '../lib/image_zoom.js'

// The one full-size image viewer (G-Eskayo/marvin#402), used by MR Review (PrImages), Docs, Files and the Portfolio
// zoom. Owner, 2026-10-21: "the only way I can get out of images is like with esc and not the x or clicking outside the
// image ... and being able to zoom in especially when you give me full page screen shots".
//
// Closing: ✕, Esc, or a click anywhere that is not the picture or a control. Why ✕ never worked: the window has a
// hidden title bar, so the app's header strip is a `-webkit-app-region: drag` area (index.css .titlebar). Electron
// hit-tests drag regions in the native window, ABOVE the page, so a fixed overlay drawn over the header still loses
// every click there to "drag the window" — and the ✕ sat right on top of the header. The overlay therefore declares
// itself `no-drag`, which removes the drag area beneath it while it is open.
//
// Zoom: pinch or ⌘-scroll (at the pointer), + / − / Fit / 100%, double-click toggles Fit ↔ 100%, drag to pan once the
// picture is bigger than the window. Opens at Fit; a tall full-page screenshot opens fit-to-width and scrolls.
// Look kept from the MR Review viewer it replaces (black backdrop, top bar, caption below).
//
// items: [{ src, kind: 'image' | 'video', status: 'ok' | 'loading' | 'error', reason, alt, caption, group }]
export default function ImageViewer({ items, index = 0, onIndex, onClose }) {
  const list = Array.isArray(items) ? items.filter(Boolean) : []
  const count = list.length
  const i = Math.min(Math.max(0, index || 0), Math.max(0, count - 1))
  const item = list[i] || {}
  const status = item.status || (item.src ? 'ok' : 'loading')
  const isImage = status === 'ok' && item.kind !== 'video'

  const scrollRef = useRef(null)
  const imgRef = useRef(null)
  const [natural, setNatural] = useState(null)
  const [fit, setFit] = useState(1)
  const [scale, setScale] = useState(1)
  const scaleRef = useRef(1)
  const pendingScroll = useRef(null)
  const drag = useRef(null)
  const dragged = useRef(false)
  scaleRef.current = scale
  const fitRef = useRef(fit)
  fitRef.current = fit

  const go = (step) => count > 1 && onIndex?.((i + step + count) % count)

  const viewport = () => {
    const el = scrollRef.current
    return el ? { w: el.clientWidth, h: el.clientHeight } : { w: 0, h: 0 }
  }

  // Zoom to `next`, keeping the image point under `point` (viewport coords; default: the centre) where it is.
  const zoomTo = (next, point) => {
    const el = scrollRef.current
    const from = scaleRef.current
    const to = clampScale(next)
    if (!el || !natural || to === from) return
    const p = point || { x: el.clientWidth / 2, y: el.clientHeight / 2 }
    pendingScroll.current = {
      left: zoomScroll({ scroll: el.scrollLeft, point: p.x, client: el.clientWidth, natural: natural.w, from, to }),
      top: zoomScroll({ scroll: el.scrollTop, point: p.y, client: el.clientHeight, natural: natural.h, from, to })
    }
    scaleRef.current = to
    setScale(to)
  }
  const zoomRef = useRef(zoomTo)
  zoomRef.current = zoomTo

  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && pendingScroll.current) {
      el.scrollLeft = pendingScroll.current.left
      el.scrollTop = pendingScroll.current.top
      pendingScroll.current = null
    }
  }, [scale])

  // A new item starts unmeasured: it opens at Fit once its size is known.
  useEffect(() => {
    setNatural(null)
  }, [i, item.src])

  const onLoad = () => {
    const img = imgRef.current
    if (!img || !img.naturalWidth) return
    const n = { w: img.naturalWidth, h: img.naturalHeight }
    const f = fitScale(n, viewport())
    setNatural(n)
    setFit(f)
    scaleRef.current = f
    setScale(f)
    pendingScroll.current = { left: 0, top: 0 }
  }

  useEffect(() => {
    const onKey = (e) => {
      const action = viewerKey(e)
      if (!action) return
      e.preventDefault()
      if (action === 'close') onClose?.()
      else if (action === 'next') go(1)
      else if (action === 'prev') go(-1)
      else if (action === 'in') zoomRef.current(stepScale(scaleRef.current, 1))
      else if (action === 'out') zoomRef.current(stepScale(scaleRef.current, -1))
      else if (action === 'fit') zoomRef.current(fitRef.current)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [count, i, onClose])

  // Pinch / ⌘-scroll zoom needs a non-passive listener to stop the page zooming or scrolling instead.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onWheel = (e) => {
      const factor = wheelZoomFactor(e)
      if (factor === null) return
      e.preventDefault()
      const r = el.getBoundingClientRect()
      zoomRef.current(scaleRef.current * factor, { x: e.clientX - r.left, y: e.clientY - r.top })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // Drag to pan, only when the picture is bigger than the window. A drag never counts as a click outside.
  useEffect(() => {
    const onMove = (e) => {
      const d = drag.current
      const el = scrollRef.current
      if (!d || !el) return
      const dx = e.clientX - d.x
      const dy = e.clientY - d.y
      if (Math.abs(dx) + Math.abs(dy) > 3) dragged.current = true
      el.scrollLeft = d.left - dx
      el.scrollTop = d.top - dy
    }
    const onUp = () => { drag.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  const pannable = () => {
    const el = scrollRef.current
    return !!(el && natural && (natural.w * scale > el.clientWidth + 1 || natural.h * scale > el.clientHeight + 1))
  }

  const pointIn = (e) => {
    const r = scrollRef.current.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }

  // Clicks on the picture and on controls stop here; anything else that reaches the backdrop closes the viewer.
  const keep = (fn) => (e) => {
    e.stopPropagation()
    fn?.(e)
  }
  const onBackdropClick = () => {
    if (dragged.current) {
      dragged.current = false
      return
    }
    onClose?.()
  }

  const touchX = useRef(null)
  const header = [item.group, count > 1 ? `${i + 1} of ${count}` : null].filter(Boolean).join(' · ')
  const btn = 'rounded px-2 py-1 hover:bg-neutral-800'
  const sized = natural ? { width: natural.w * scale, height: natural.h * scale, maxWidth: 'none' } : { maxWidth: '100%' }

  return (
    <div
      role="dialog"
      aria-label="Image viewer"
      data-image-viewer=""
      style={{ WebkitAppRegion: 'no-drag' }}
      className="fixed inset-0 z-50 flex flex-col bg-black/95"
      onClick={onBackdropClick}
      onTouchStart={(e) => { touchX.current = e.touches[0].clientX }}
      onTouchEnd={(e) => {
        if (touchX.current === null || scale > fit + 0.001) { touchX.current = null; return }
        const dx = e.changedTouches[0].clientX - touchX.current
        touchX.current = null
        if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1)
      }}
    >
      <div className="flex items-center justify-between gap-2 p-3 text-sm text-neutral-300">
        <span className="truncate">{header}</span>
        <div className="flex shrink-0 items-center gap-1">
          {isImage && (
            <>
              <button onClick={keep(() => zoomTo(stepScale(scale, -1)))} className={btn} aria-label="Zoom out" title="Zoom out (−)">−</button>
              <span className="w-12 text-center tabular-nums text-neutral-400" aria-label="Zoom level">{Math.round(scale * 100)}%</span>
              <button onClick={keep(() => zoomTo(stepScale(scale, 1)))} className={btn} aria-label="Zoom in" title="Zoom in (+)">+</button>
              <button onClick={keep(() => zoomTo(fit))} className={btn} aria-label="Fit" title="Fit (0)">Fit</button>
              <button onClick={keep(() => zoomTo(1))} className={btn} aria-label="Actual size" title="Actual size">100%</button>
            </>
          )}
          <button onClick={keep(onClose)} className={btn} aria-label="Close">✕ Close</button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 items-stretch gap-2 px-2">
        {count > 1 && <button onClick={keep(() => go(-1))} className="self-center rounded px-3 py-6 text-2xl text-neutral-400 hover:bg-neutral-800" aria-label="Previous">‹</button>}
        <div ref={scrollRef} data-viewer-scroll="" className="min-h-0 min-w-0 flex-1 overflow-auto">
          {/* min 100% both ways + margin:auto centres a small picture and lets a big one scroll from its top-left. */}
          <div style={{ display: 'flex', minWidth: '100%', minHeight: '100%', width: 'max-content' }}>
            {status === 'ok' ? (
              item.kind === 'video' ? (
                <video src={item.src} aria-label={item.alt || 'Recording'} onClick={keep()} style={{ margin: 'auto', maxWidth: '100%', maxHeight: '100%' }} controls loop muted playsInline autoPlay />
              ) : (
                <img
                  ref={imgRef}
                  src={item.src}
                  alt={item.alt || item.caption || ''}
                  draggable={false}
                  onLoad={onLoad}
                  onClick={keep()}
                  onDoubleClick={keep((e) => zoomTo(toggleScale(scale, fit), pointIn(e)))}
                  onMouseDown={(e) => {
                    if (e.button !== 0 || !pannable()) return
                    e.preventDefault()
                    dragged.current = false
                    drag.current = { x: e.clientX, y: e.clientY, left: scrollRef.current.scrollLeft, top: scrollRef.current.scrollTop }
                  }}
                  style={{ margin: 'auto', ...sized, cursor: natural && pannable() ? 'grab' : 'default' }}
                />
              )
            ) : (
              <p className="m-auto text-center text-sm text-neutral-400">{status === 'error' ? `couldn't load: ${item.reason || 'unknown error'}` : 'Loading…'}</p>
            )}
          </div>
        </div>
        {count > 1 && <button onClick={keep(() => go(1))} className="self-center rounded px-3 py-6 text-2xl text-neutral-400 hover:bg-neutral-800" aria-label="Next">›</button>}
      </div>
      {item.caption && <p className="p-3 text-center text-sm text-neutral-300">{item.caption}</p>}
    </div>
  )
}

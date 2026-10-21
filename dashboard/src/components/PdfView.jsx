import { useEffect, useRef, useState } from 'react'
import { openPdf, pageScale, viewerScale, pageCountLabel } from '../lib/pdf_doc.js'

// The Files tab's own PDF renderer (G-Eskayo/marvin#402). Replaces Chromium's embedded viewer, which Gil found "looks
// really trashy UI and UX wise": it didn't fill the panel and brought its own light-grey toolbar, thumbnails and zoom.
// Pages are drawn with pdf.js into canvases, stacked in one scrolling column at the panel's width, in the dashboard's
// dark style. Clicking a page opens it, rendered sharp, in the shared ImageViewer, so zoom works exactly like images.
//
// pdf.js and its worker are loaded on first use from the app bundle (Vite emits the worker as an asset), so the CSP's
// script-src 'self' covers the worker and nothing touches the network. No eval (isEvalSupported: false).
//
// Cost for an N-page PDF: opening reads page 1 only. Each page is a placeholder sized from page 1's shape (O(N) light
// DOM nodes, no rendering); a page renders only while it is within about 1.5 screens of the viewport and its canvas is
// released when it scrolls away, so render time is O(pages scrolled past) and canvas memory O(pages near the viewport)
// — a 200-page PDF holds two or three canvases, not 200.

let pdfjsPromise = null
export function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')])
      .then(([pdfjs, worker]) => {
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default
        return pdfjs
      })
      .catch((err) => {
        pdfjsPromise = null
        throw err
      })
  }
  return pdfjsPromise
}

// The nearest scrolling ancestor: the observer's root must be the panel that scrolls, or its margin (1.5 screens of
// look-ahead) is clipped away and pages only start drawing once already on screen.
function scrollParent(el) {
  for (let p = el?.parentElement; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY
    if (o === 'auto' || o === 'scroll') return p
  }
  return null
}

function PdfPage({ doc, number, width, aspect, onOpen }) {
  const boxRef = useRef(null)
  const canvasRef = useRef(null)
  const [near, setNear] = useState(false)
  const [shape, setShape] = useState(null) // this page's own height/width, once known
  const [rendered, setRendered] = useState(false)

  useEffect(() => {
    const el = boxRef.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(([entry]) => setNear(entry.isIntersecting), { root: scrollParent(el), rootMargin: '150% 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    if (!near || !width) {
      canvas.width = 0 // releases the backing store
      canvas.height = 0
      setRendered(false)
      return
    }
    let task = null
    let live = true
    doc.getPage(number).then((page) => {
      if (!live) return
      const base = page.getViewport({ scale: 1 })
      setShape(base.height / base.width)
      const { css, pixel } = pageScale(base.width, base.height, width, window.devicePixelRatio || 1)
      const vp = page.getViewport({ scale: pixel })
      canvas.width = Math.floor(vp.width)
      canvas.height = Math.floor(vp.height)
      canvas.style.width = `${base.width * css}px`
      canvas.style.height = `${base.height * css}px`
      task = page.render({ canvasContext: canvas.getContext('2d'), viewport: vp })
      return task.promise.then(() => live && setRendered(true))
    }).catch(() => { /* cancelled, or a page pdf.js can't draw: the placeholder stays */ })
    return () => {
      live = false
      task?.cancel()
    }
  }, [near, width, doc, number])

  const height = width ? width * (shape || aspect) : undefined
  return (
    <div
      ref={boxRef}
      data-pdf-page={number}
      data-rendered={rendered ? '1' : '0'}
      style={{ width: width || '100%', height }}
      className="relative mx-auto cursor-zoom-in overflow-hidden rounded bg-neutral-900 shadow-lg shadow-black/40"
      onClick={() => onOpen(number)}
      title={`Page ${number} · click to zoom`}
    >
      <canvas ref={canvasRef} className="block bg-white" aria-label={`Page ${number}`} />
    </div>
  )
}

// file: { name, data: Uint8Array }. onOpenImage({ src, alt }) opens the shared viewer; onOpen() opens the file in
// Preview; card(reason) renders the FileView card for a PDF pdf.js can't read.
export default function PdfView({ file, onOpenImage, onOpen, card }) {
  const wrapRef = useRef(null)
  const [state, setState] = useState({ status: 'loading' })
  const [width, setWidth] = useState(0)
  const [opening, setOpening] = useState(null)

  useEffect(() => {
    let live = true
    let doc = null
    setState({ status: 'loading' })
    loadPdfjs()
      .then((pdfjs) => openPdf(pdfjs.getDocument, file.data))
      .then((r) => {
        if (!live) return r.doc?.destroy()
        doc = r.doc || null
        setState(r.ok ? { status: 'ok', ...r } : { status: 'error', reason: r.reason })
      })
      .catch((err) => live && setState({ status: 'error', reason: `The PDF reader couldn't start (${err?.message || err}).` }))
    return () => {
      live = false
      doc?.destroy()
    }
  }, [file.data])

  useEffect(() => {
    const el = wrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [state.status])

  // A clicked page, rendered at about 4096 px on its long side, opens in the shared viewer.
  const openPage = async (n) => {
    if (opening || state.status !== 'ok') return
    setOpening(n)
    try {
      const page = await state.doc.getPage(n)
      const base = page.getViewport({ scale: 1 })
      const vp = page.getViewport({ scale: viewerScale(base.width, base.height) })
      const canvas = document.createElement('canvas')
      canvas.width = Math.floor(vp.width)
      canvas.height = Math.floor(vp.height)
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      await page.render({ canvasContext: ctx, viewport: vp }).promise
      onOpenImage?.({ src: canvas.toDataURL('image/png'), alt: `${file.name} · page ${n} of ${state.numPages}` })
      canvas.width = 0
    } catch {
      /* leave the column as it is */
    } finally {
      setOpening(null)
    }
  }

  if (state.status === 'error') return card(state.reason)
  if (state.status === 'loading') return <p className="text-sm text-neutral-500">Loading PDF…</p>
  const pages = Array.from({ length: state.numPages }, (_, i) => i + 1)
  return (
    <div>
      <div className="mb-3 flex items-center gap-3 text-xs text-neutral-400">
        <span data-pdf-count="">{pageCountLabel(state.numPages)}</span>
        {onOpen && (
          <button onClick={onOpen} className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500">
            Open in Preview
          </button>
        )}
        {opening && <span>Opening page {opening}…</span>}
      </div>
      <div ref={wrapRef} className="flex flex-col gap-4">
        {pages.map((n) => <PdfPage key={n} doc={state.doc} number={n} width={width} aspect={state.aspect} onOpen={openPage} />)}
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import 'pdfjs-dist/web/pdf_viewer.css'
import './pdf_view.css'
import { openPdf, viewerScale, pageCountLabel } from '../lib/pdf_doc.js'
import { safeExternalUrl, parsePageInput, normalizeOutline, findStatus } from '../lib/pdf_nav.js'

// The Files tab's interactive PDF view (G-Eskayo/marvin#402). Chromium's embedded viewer was rejected (Gil: "looks really
// trashy UI and UX wise"); then, for large PDFs, Gil asked to keep what it offered: jump to pages, follow links, fill
// forms. So this is pdf.js's own viewer component (PDFViewer, with its text, link and form layers and its find
// controller) inside the dashboard's dark style, with a compact toolbar of our own.
//
// Safety: pdf.js and its worker load from the app bundle (CSP script-src 'self'); no eval; nothing is fetched. JavaScript
// inside a PDF never runs: no scripting manager is created. External links open only through outbox:openLink, which
// allows http/https/mailto (safeExternalUrl, re-checked in main). Form edits stay in memory; the file is never written.
//
// Cost for an N-page PDF: opening reads page 1 (shape) and, because getDocument gets disableAutoFetch, PDFViewer sets
// the other pages up lazily (no per-page fetch on open). It renders the visible pages plus the next one and keeps a
// bounded cache of rendered pages (pdf.js DEFAULT_CACHE_SIZE, 10), destroying older canvases: render time is O(pages
// viewed), canvas memory O(1) in N. Jumping to page 400 renders page 400 and its neighbours only. Find walks the text
// of every page (O(N) text extraction, done by pdf.js only when a search runs).

let pdfjsPromise = null
export function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = (async () => {
      const pdfjs = await import('pdfjs-dist') // sets globalThis.pdfjsLib, which the viewer module reads
      const [viewer, worker] = await Promise.all([import('pdfjs-dist/web/pdf_viewer.mjs'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')])
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default
      return { pdfjs, viewer }
    })().catch((err) => {
      pdfjsPromise = null
      throw err
    })
  }
  return pdfjsPromise
}

const btn = 'rounded border border-neutral-700 px-2 py-0.5 text-xs text-neutral-200 hover:border-neutral-500 disabled:opacity-40'
const iconBtn = 'rounded px-1.5 py-0.5 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-40'

function OutlineList({ items, onPick, depth = 0 }) {
  return (
    <ul className={depth ? 'ml-3 border-l border-neutral-800 pl-2' : ''}>
      {items.map((it, i) => (
        <li key={i}>
          <button onClick={() => onPick(it)} className="block w-full truncate rounded px-1 py-0.5 text-left text-xs text-neutral-300 hover:bg-neutral-800 hover:text-white" title={it.title}>
            {it.title}
          </button>
          {it.items.length > 0 && <OutlineList items={it.items} onPick={onPick} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  )
}

// file: { name, data: Uint8Array }. onOpenImage({ src, alt }) opens the shared viewer; onOpen() opens the file in
// Preview; onOpenLink(url) opens a safe external link; card(reason) renders the FileView card for an unreadable PDF.
export default function PdfView({ file, onOpenImage, onOpen, onOpenLink, card }) {
  const scrollRef = useRef(null)
  const innerRef = useRef(null)
  const findRef = useRef(null)
  const ctl = useRef(null) // { viewer, eventBus, linkService }
  const [state, setState] = useState({ status: 'loading' })
  const [page, setPage] = useState(1)
  const [pageInput, setPageInput] = useState('1')
  const [scale, setScale] = useState(1)
  const [outline, setOutline] = useState([])
  const [showOutline, setShowOutline] = useState(true)
  const [hasForm, setHasForm] = useState(false)
  const [find, setFind] = useState({ open: false, query: '', total: 0, current: 0 })
  const [opening, setOpening] = useState(false)

  useEffect(() => {
    let live = true
    let doc = null
    setState({ status: 'loading' })
    loadPdfjs()
      .then(({ pdfjs, viewer }) => openPdf(pdfjs.getDocument, file.data).then((r) => ({ r, pdfjs, viewer })))
      .then(({ r, pdfjs, viewer }) => {
        if (!live) return r.doc?.destroy()
        doc = r.doc || null
        setState(r.ok ? { status: 'ok', ...r, pdfjs, lib: viewer } : { status: 'error', reason: r.reason })
      })
      .catch((err) => live && setState({ status: 'error', reason: `The PDF reader couldn't start (${err?.message || err}).` }))
    return () => {
      live = false
      doc?.destroy()
    }
  }, [file.data])

  // Build pdf.js's viewer once the document is open.
  useEffect(() => {
    if (state.status !== 'ok') return
    const { doc, pdfjs, lib } = state
    const container = scrollRef.current
    const eventBus = new lib.EventBus()
    const linkService = new lib.PDFLinkService({ eventBus, externalLinkTarget: lib.LinkTarget.BLANK, externalLinkRel: 'noopener noreferrer nofollow' })
    const findController = new lib.PDFFindController({ eventBus, linkService })
    const viewer = new lib.PDFViewer({
      container, viewer: innerRef.current, eventBus, linkService, findController,
      textLayerMode: 1, annotationMode: pdfjs.AnnotationMode.ENABLE_FORMS, removePageBorders: true
    })
    linkService.setViewer(viewer)
    ctl.current = { viewer, eventBus, linkService }
    eventBus.on('pagesinit', () => { viewer.currentScaleValue = 'page-width' })
    eventBus.on('pagechanging', (e) => { setPage(e.pageNumber); setPageInput(String(e.pageNumber)) })
    eventBus.on('scalechanging', (e) => setScale(e.scale))
    eventBus.on('updatefindmatchescount', (e) => setFind((f) => ({ ...f, total: e.matchesCount?.total || 0, current: e.matchesCount?.current || 0 })))
    eventBus.on('updatefindcontrolstate', (e) => setFind((f) => ({ ...f, total: e.matchesCount?.total || 0, current: e.matchesCount?.current || 0 })))
    viewer.setDocument(doc)
    linkService.setDocument(doc, null)
    doc.getOutline().then((o) => setOutline(normalizeOutline(o))).catch(() => setOutline([]))
    doc.getFieldObjects().then((f) => setHasForm(!!f && Object.keys(f).length > 0)).catch(() => {})

    // Links: internal ones (href "#…") are pdf.js's; every other link is stopped here and only a safe one leaves.
    const onClick = (e) => {
      const a = e.target.closest?.('a[href]')
      if (!a || !container.contains(a)) return
      const href = a.getAttribute('href') || ''
      if (href.startsWith('#')) return
      e.preventDefault()
      e.stopPropagation()
      const safe = safeExternalUrl(a.href)
      if (safe) onOpenLink?.(safe)
    }
    container.addEventListener('click', onClick, true)
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => {
      if (viewer.currentScaleValue === 'page-width') viewer.currentScaleValue = 'page-width'
    }) : null
    ro?.observe(container)
    return () => {
      container.removeEventListener('click', onClick, true)
      ro?.disconnect()
      viewer.setDocument(null)
      linkService.setDocument(null)
      ctl.current = null
    }
  }, [state])

  useEffect(() => {
    if (find.open) findRef.current?.select()
  }, [find.open])

  const go = (n) => {
    const v = ctl.current?.viewer
    if (v && n >= 1 && n <= state.numPages) v.currentPageNumber = n
  }
  const jump = () => {
    const n = parsePageInput(pageInput, state.numPages)
    if (n) go(n)
    else setPageInput(String(page))
  }
  const zoom = (dir) => {
    const v = ctl.current?.viewer
    if (!v) return
    if (dir > 0) v.increaseScale()
    else v.decreaseScale()
  }
  const runFind = (type, findPrevious = false, query = find.query) => {
    ctl.current?.eventBus.dispatch('find', { source: null, type, query, caseSensitive: false, entireWord: false, highlightAll: true, findPrevious, matchDiacritics: false })
  }
  const openFind = () => {
    if (find.open) findRef.current?.select()
    else setFind((f) => ({ ...f, open: true }))
  }
  const closeFind = () => {
    ctl.current?.eventBus.dispatch('findbarclose', { source: null })
    setFind({ open: false, query: '', total: 0, current: 0 })
    scrollRef.current?.focus()
  }
  const onKeyDown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'f') {
      e.preventDefault()
      e.stopPropagation()
      openFind()
    }
  }
  const pickOutline = (it) => {
    if (it.dest) ctl.current?.linkService.goToDestination(it.dest)
    else if (it.url) onOpenLink?.(it.url)
  }

  // The current page, rendered at about 4096 px on its long side, opens in the shared image viewer.
  const fullSize = async () => {
    if (opening || state.status !== 'ok') return
    setOpening(true)
    try {
      const pg = await state.doc.getPage(page)
      const base = pg.getViewport({ scale: 1 })
      const vp = pg.getViewport({ scale: viewerScale(base.width, base.height) })
      const canvas = document.createElement('canvas')
      canvas.width = Math.floor(vp.width)
      canvas.height = Math.floor(vp.height)
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      await pg.render({ canvasContext: ctx, viewport: vp }).promise
      onOpenImage?.({ src: canvas.toDataURL('image/png'), alt: `${file.name} · page ${page} of ${state.numPages}` })
      canvas.width = 0
    } catch {
      /* leave things as they are */
    } finally {
      setOpening(false)
    }
  }

  if (state.status === 'error') return card(state.reason)
  if (state.status === 'loading') return <p className="text-sm text-neutral-500">Loading PDF…</p>
  const n = state.numPages
  return (
    <div className="marvin-pdf flex h-full min-h-[70vh] flex-col" onKeyDown={onKeyDown}>
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-400" data-pdf-toolbar="">
        {outline.length > 0 && (
          <button onClick={() => setShowOutline((s) => !s)} className={btn} aria-pressed={showOutline} title="Show or hide the outline">☰ Outline</button>
        )}
        <span data-pdf-count="">{pageCountLabel(n)}</span>
        <span className="flex items-center gap-1">
          <button onClick={() => go(page - 1)} disabled={page <= 1} className={iconBtn} aria-label="Previous page">‹</button>
          <span>page</span>
          <input
            value={pageInput}
            onChange={(e) => setPageInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') jump() }}
            onBlur={() => setPageInput(String(page))}
            aria-label="Page number"
            data-pdf-page-input=""
            className="w-12 rounded border border-neutral-700 bg-neutral-900 px-1 py-0.5 text-center text-xs text-neutral-100"
          />
          <span>of {n}</span>
          <button onClick={() => go(page + 1)} disabled={page >= n} className={iconBtn} aria-label="Next page">›</button>
        </span>
        <span className="flex items-center gap-1">
          <button onClick={() => zoom(-1)} className={iconBtn} aria-label="Zoom out">−</button>
          <span className="w-10 text-center tabular-nums" aria-label="Zoom level">{Math.round(scale * 100)}%</span>
          <button onClick={() => zoom(1)} className={iconBtn} aria-label="Zoom in">+</button>
          <button onClick={() => { if (ctl.current) ctl.current.viewer.currentScaleValue = 'page-width' }} className={btn}>Fit width</button>
        </span>
        <button onClick={find.open ? closeFind : openFind} className={btn} title="Find in this PDF (⌘F)">Find</button>
        <button onClick={fullSize} className={btn} disabled={opening} title="Open this page full size">{opening ? 'Opening…' : '⤢ Full size'}</button>
        {onOpen && <button onClick={onOpen} className={btn}>Open in Preview</button>}
        {hasForm && <span className="text-amber-300/80" data-pdf-form-note="">Form edits stay here and aren't saved to the file.</span>}
      </div>
      {find.open && (
        <div className="mb-2 flex items-center gap-2 text-xs text-neutral-400" data-pdf-find="">
          <input
            ref={findRef}
            value={find.query}
            onChange={(e) => { const q = e.target.value; setFind((f) => ({ ...f, query: q })); runFind('', false, q) }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); runFind('again', e.shiftKey) }
              else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeFind() }
            }}
            placeholder="Find in PDF"
            aria-label="Find in PDF"
            className="w-56 rounded border border-neutral-700 bg-neutral-900 px-2 py-0.5 text-xs text-neutral-100"
          />
          <button onClick={() => runFind('again', true)} disabled={!find.total} className={iconBtn} aria-label="Previous match">↑</button>
          <button onClick={() => runFind('again', false)} disabled={!find.total} className={iconBtn} aria-label="Next match">↓</button>
          <span data-pdf-find-status="">{findStatus(find)}</span>
          <button onClick={closeFind} className={iconBtn} aria-label="Close find">✕</button>
        </div>
      )}
      <div className="flex min-h-0 flex-1 overflow-hidden rounded border border-neutral-800">
        {outline.length > 0 && showOutline && (
          <aside className="w-56 shrink-0 overflow-auto border-r border-neutral-800 p-2" data-pdf-outline="">
            <p className="mb-1 px-1 text-[10px] uppercase tracking-wide text-neutral-500">Outline</p>
            <OutlineList items={outline} onPick={pickOutline} />
          </aside>
        )}
        <div className="relative min-w-0 flex-1">
          <div ref={scrollRef} tabIndex={0} className="marvin-pdf-scroll absolute inset-0 overflow-auto" data-pdf-scroll="">
            <div ref={innerRef} className="pdfViewer" />
          </div>
        </div>
      </div>
    </div>
  )
}

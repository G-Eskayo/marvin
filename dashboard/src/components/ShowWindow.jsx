import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import '@fontsource/saira-condensed/600.css'
import '@fontsource/share-tech-mono/400.css'
import FileView, { FileCard } from './FileView.jsx'
import './show_window.css'

// A `marvin show` window (G-Eskayo/marvin#715): one project's window, showing only the item a session asked for.
// The Docs viewer (FileView) draws files, as in the Docs tab; an HTML page runs in a sandboxed frame served by the
// main process (show_window.js) with no access to the app. A web address renders in the window, in its own isolated
// view laid over the box this page reserves (show_web.js), with "Open in browser" always in the header and the link
// card as the fallback when the page can't be drawn. The look is the celestial-navigation tokens (#428), as the owner
// chose on PR #1029.

const KIND_TAG = { html: 'Page', link: 'Web', image: 'Image', pdf: 'PDF', markdown: 'Doc', text: 'Text' }

export function itemTag(item) {
  if (!item) return null
  if (item.pr?.number) return `PR #${item.pr.number}`
  return KIND_TAG[item.kind] || 'File'
}

export function LinkCard({ url, reason, api }) {
  return (
    <div className="show-card" data-show-link="">
      {reason && <p className="show-reason" data-show-reason="">{reason}</p>}
      <p className="show-card-url">{url}</p>
      <button onClick={() => api.openLink(url)} className="show-btn mt-3">Open in browser</button>
    </div>
  )
}

// The box the web page is drawn into. Its place in the window is sent to the main process whenever it changes.
export function WebArea({ item, api }) {
  const ref = useRef(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !api.setWebBounds) return
    const send = () => {
      const r = el.getBoundingClientRect()
      api.setWebBounds({ x: r.left, y: r.top, width: r.width, height: r.height })
    }
    send()
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(send) : null
    ro?.observe(el)
    window.addEventListener('resize', send)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', send)
    }
  }, [item?.url, api])
  return (
    <div ref={ref} className="show-web h-full w-full" data-show-web={item.web?.state || 'loading'}>
      <p className="show-empty">Loading {item.url}…</p>
    </div>
  )
}

export function ShowBody({ item, file, error, api }) {
  if (error) return <FileCard file={{ name: item?.label || 'This item', label: '' }} reason={error} />
  if (!item) return <p className="show-empty">Nothing shown yet.</p>
  if (item.kind === 'link') {
    // Drawn in the window when this Mac can (item.web); otherwise, or when it failed, the link card says why.
    if (item.web && item.web.state !== 'failed') return <WebArea item={item} api={api} />
    return <LinkCard url={item.web?.url || item.url} reason={item.web?.reason} api={api} />
  }
  if (item.kind === 'html') {
    // allow-scripts only: an opaque origin (no allow-same-origin), no pop-ups, no top navigation, no forms.
    return <iframe key={item.frameUrl} title={item.label} src={item.frameUrl} sandbox="allow-scripts" data-show-frame="" className="show-frame h-full min-h-[calc(100vh-5rem)] w-full" />
  }
  if (!file) return <p className="show-empty">Loading…</p>
  return <FileView file={file} loadImage={(src) => api.image(src)} fitImage />
}

// The history strip (#715): this project's earlier items, newest first; a click shows that one again here.
export function HistoryStrip({ history = [], currentId, onSelect }) {
  if (history.length < 2) return null
  return (
    <nav className="show-history flex gap-2 overflow-x-auto px-3 py-2" data-history-strip="">
      {history.map((h) => {
        const on = h.id === currentId
        return (
          <button
            key={h.id}
            onClick={() => !on && onSelect(h.id)}
            title={h.label}
            aria-current={on ? 'true' : undefined}
            className={`show-history-item shrink-0 max-w-[14rem] text-left${on ? ' is-current' : ''}`}
          >
            <span className="show-history-label block truncate">{h.label}</span>
            <span className="show-history-meta block">{itemTag(h)} · {new Date(h.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          </button>
        )
      })}
    </nav>
  )
}

export default function ShowWindow({ project, api = window.api.show, initialItem = null }) {
  const [item, setItem] = useState(initialItem)
  const [file, setFile] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const select = (id) => {
    setNotice(null)
    api.select(id).then((r) => !r?.ok && setNotice(r?.reason || 'That item can\'t be shown any more')).catch((err) => setNotice(String(err?.message || err)))
  }

  useEffect(() => {
    let live = true
    const take = (next) => {
      if (!live) return
      setItem(next)
      setFile(null)
      setError(null)
      if (next && next.kind !== 'html' && next.kind !== 'link') {
        api.read()
          .then((f) => live && setFile(f))
          .catch((err) => live && setError(String(err?.message || err)))
      }
    }
    api.current().then(take).catch(() => {})
    const off = api.onItem(take)
    // The web page's state (loading, loaded, failed) and the address it is on now.
    const offWeb = api.onWeb?.((web) => live && setItem((it) => (it && it.kind === 'link' ? { ...it, web } : it)))
    return () => {
      live = false
      off?.()
      offWeb?.()
    }
  }, [])

  useEffect(() => {
    document.title = `MARVIN · ${item?.project?.name || project}`
  }, [item, project])

  const isWeb = item?.kind === 'link' && item.web && item.web.state !== 'failed'
  const linkUrl = item?.kind === 'link' ? item.web?.url || item.url : null
  return (
    <div className="show-root flex h-screen flex-col" data-show-window={project}>
      <header className="show-hud flex items-center gap-3 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="show-project truncate">{item?.project?.name || project}</p>
          <p className="show-label truncate" title={item?.path || item?.url || ''}>{item?.label || ' '}</p>
        </div>
        {item && <span className="show-tag" data-show-tag="">{itemTag(item)}</span>}
        {linkUrl && (
          <button onClick={() => api.openLink(linkUrl)} className="show-btn" data-show-open-browser="">Open in browser</button>
        )}
        {item && (
          <button onClick={() => api.openInDocs()} className="show-btn">Open in Docs</button>
        )}
      </header>
      <HistoryStrip history={item?.history || []} currentId={item?.historyId} onSelect={select} />
      {notice && <p className="show-notice px-3 py-1" data-show-notice="">{notice}</p>}
      <main className={`min-h-0 flex-1 ${isWeb ? 'overflow-hidden' : 'overflow-auto p-3'}`}>
        <ShowBody item={item} file={file} error={error} api={api} />
      </main>
    </div>
  )
}

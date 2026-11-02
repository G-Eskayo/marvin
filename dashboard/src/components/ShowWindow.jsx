import { useEffect, useState } from 'react'
import FileView, { FileCard } from './FileView.jsx'

// A `marvin show` window (G-Eskayo/marvin#715): one project's window, showing only the item a session asked for.
// The Docs viewer (FileView) draws files, as in the Docs tab; an HTML page runs in a sandboxed frame served by the
// main process (show_window.js) with no access to the app; a web address is a link Gil opens in his browser.
// The look is the mock-up look until Gil signs it off (the tag in the header says so).

export const MOCKUP_TAG = 'Mock-up look, waiting for sign-off'

export function ShowBody({ item, file, error, api }) {
  if (error) return <FileCard file={{ name: item?.label || 'This item', label: '' }} reason={error} />
  if (!item) return <p className="text-sm text-neutral-500">Nothing shown yet.</p>
  if (item.kind === 'link') {
    return (
      <div className="max-w-xl rounded-lg border border-neutral-800 p-4" data-show-link="">
        <p className="break-all text-sm text-neutral-100">{item.url}</p>
        <button onClick={() => api.openLink(item.url)} className="mt-3 rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500">
          Open in browser
        </button>
      </div>
    )
  }
  if (item.kind === 'html') {
    // allow-scripts only: an opaque origin (no allow-same-origin), no pop-ups, no top navigation, no forms.
    return <iframe key={item.frameUrl} title={item.label} src={item.frameUrl} sandbox="allow-scripts" data-show-frame="" className="h-full min-h-[calc(100vh-5rem)] w-full rounded border border-neutral-800 bg-white" />
  }
  if (!file) return <p className="text-sm text-neutral-500">Loading…</p>
  return <FileView file={file} loadImage={(src) => api.image(src)} fitImage />
}

const KIND_WORD = { image: 'Image', pdf: 'PDF', markdown: 'Markdown', html: 'Page', link: 'Link', json: 'JSON', table: 'Table', code: 'Code', text: 'Text', notebook: 'Notebook' }

// The history strip (#715): this project's earlier items, newest first; a click shows that one again here.
export function HistoryStrip({ history = [], currentId, onSelect }) {
  if (history.length < 2) return null
  return (
    <nav className="flex gap-2 overflow-x-auto border-b border-neutral-800 px-3 py-2" data-history-strip="">
      {history.map((h) => {
        const on = h.id === currentId
        return (
          <button
            key={h.id}
            onClick={() => !on && onSelect(h.id)}
            title={h.label}
            aria-current={on ? 'true' : undefined}
            className={`shrink-0 max-w-[14rem] rounded border px-2 py-1 text-left text-xs ${on ? 'border-amber-600/70 text-neutral-100' : 'border-neutral-800 text-neutral-400 hover:border-neutral-600'}`}
          >
            <span className="block truncate">{h.label}</span>
            <span className="block text-[10px] text-neutral-500">{KIND_WORD[h.kind] || 'File'} · {new Date(h.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          </button>
        )
      })}
    </nav>
  )
}

export default function ShowWindow({ project, api = window.api.show }) {
  const [item, setItem] = useState(null)
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
    return () => {
      live = false
      off?.()
    }
  }, [])

  useEffect(() => {
    document.title = `MARVIN · ${item?.project?.name || project}`
  }, [item, project])

  return (
    <div className="flex h-screen flex-col bg-[#0f1117] text-white" data-show-window={project}>
      <header className="flex items-center gap-3 border-b border-neutral-800 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs uppercase tracking-wide text-neutral-500">{item?.project?.name || project}</p>
          <p className="truncate text-sm font-medium text-neutral-100" title={item?.path || item?.url || ''}>{item?.label || ' '}</p>
        </div>
        <span className="rounded border border-amber-700/60 px-1.5 py-0.5 text-[10px] text-amber-400" data-mockup-tag="">{MOCKUP_TAG}</span>
        {item && (
          <button onClick={() => api.openInDocs()} className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500">
            Open in Docs
          </button>
        )}
      </header>
      <HistoryStrip history={item?.history || []} currentId={item?.historyId} onSelect={select} />
      {notice && <p className="border-b border-neutral-800 px-3 py-1 text-xs text-red-400" data-show-notice="">{notice}</p>}
      <main className="min-h-0 flex-1 overflow-auto p-3">
        <ShowBody item={item} file={file} error={error} api={api} />
      </main>
    </div>
  )
}

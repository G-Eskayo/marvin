import { useMemo, useState } from 'react'
import Markdown from './Markdown.jsx'
import ImageViewer from './ImageViewer.jsx'
import PdfView from './PdfView.jsx'
import { notebookToMarkdown } from '../lib/ipynb.js'
import { parseDelimited, sandboxedHtml, TABLE_ROW_LIMIT } from '../lib/file_view.js'
import { formatSize } from '../lib/file_kinds.js'

// One viewer that takes a file and picks its renderer (G-Eskayo/marvin#402), so the Files tab and the Docs tab show
// files the same way. `file` is what the main process read (outbox.js readOutboxFile):
//   { kind, label, name, path, size, content | dataUrl | data (PDF bytes) | reason }
// kinds: image, markdown, notebook, json, table, pdf, html, code, text, other (the card).
// `loadImage(src)`: bytes for a markdown file's relative images. `onReveal()`: Reveal in Finder for the card.
// `onOpenFile()`: Open in Preview (shown for PDFs). `onOpenLink(url)`: a safe external link clicked inside a PDF.
// `markdown`: extra props for Markdown (ctx, onLink) when the Docs tab uses it.

const pre = 'mb-3 overflow-auto rounded-lg bg-neutral-900 p-3 font-mono text-sm text-neutral-200'

export function FileCard({ file, onReveal, reason }) {
  return (
    <div className="max-w-md rounded-lg border border-neutral-800 p-4" data-file-card="">
      <p className="truncate text-sm font-medium text-neutral-100" title={file.name}>{file.name}</p>
      <p className="mt-1 text-xs text-neutral-400">{[file.label, formatSize(file.size)].filter(Boolean).join(' · ')}</p>
      {(reason || file.reason) && <p className="mt-2 text-xs text-neutral-500">{reason || file.reason}</p>}
      {onReveal && (
        <button onClick={onReveal} className="mt-3 rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500">
          Reveal in Finder
        </button>
      )}
    </div>
  )
}

export function DataTable({ content, delimiter }) {
  const rows = useMemo(() => parseDelimited(content, delimiter), [content, delimiter])
  if (!rows.length) return <p className="text-sm text-neutral-500">This table is empty.</p>
  const [head, ...body] = rows
  const shown = body.slice(0, TABLE_ROW_LIMIT)
  return (
    <div>
      <div className="mb-3 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>{head.map((h, i) => <th key={i} className="border border-neutral-700 bg-neutral-900 px-2 py-1 text-left font-semibold text-neutral-100">{h}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((r, ri) => (
              <tr key={ri}>{r.map((c, ci) => <td key={ci} className="whitespace-pre-wrap border border-neutral-800 px-2 py-1 align-top text-neutral-300">{c}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-neutral-500">
        {body.length > shown.length ? `Showing the first ${shown.length} of ${body.length} rows.` : `${body.length} row${body.length === 1 ? '' : 's'}.`}
      </p>
    </div>
  )
}

function prettyJson(content) {
  try {
    return JSON.stringify(JSON.parse(content), null, 2)
  } catch {
    return content
  }
}

export default function FileView({ file, loadImage, onReveal, onOpenFile, onOpenLink, markdown = {} }) {
  const [viewer, setViewer] = useState(null)
  const [broken, setBroken] = useState(false)
  const open = ({ src, alt }) => setViewer({ src, alt, caption: alt || '' })
  if (!file) return null
  const { kind } = file
  const card = (reason) => <FileCard file={file} onReveal={onReveal} reason={reason} />

  let body
  if (kind === 'image') {
    body = broken
      ? card('This image is damaged or in a format that can\'t be drawn.')
      : <img src={file.dataUrl} alt={file.name} onError={() => setBroken(true)} onClick={() => open({ src: file.dataUrl, alt: file.name })} className="h-auto max-w-full cursor-zoom-in rounded" />
  } else if (kind === 'markdown' || kind === 'notebook') {
    const text = kind === 'notebook' ? notebookToMarkdown(file.content) : file.content
    body = <Markdown content={text} loadImage={loadImage} onOpenImage={open} {...markdown} />
  } else if (kind === 'json') {
    body = <pre className={pre}>{prettyJson(file.content)}</pre>
  } else if (kind === 'table') {
    body = <DataTable content={file.content} delimiter={/\.tsv$/i.test(file.name || '') ? '\t' : ','} />
  } else if (kind === 'pdf') {
    // pdf.js's interactive viewer in the dashboard's style (owner, 2026-10-21: Chromium's embedded viewer clashed). See PdfView.
    body = <PdfView file={file} onOpenImage={open} onOpen={onOpenFile} onOpenLink={onOpenLink} card={card} />
  } else if (kind === 'html') {
    // Rendered, sandboxed: no scripts, no network (owner decision 2026-10-21). See sandboxedHtml.
    body = <iframe title={file.name} sandbox="" srcDoc={sandboxedHtml(file.content)} className="h-full min-h-[70vh] w-full rounded border border-neutral-800 bg-white" />
  } else if (kind === 'code' || kind === 'text') {
    body = <pre className={pre}>{file.content}</pre>
  } else {
    body = card()
  }

  return (
    <>
      {body}
      {viewer && <ImageViewer items={[{ src: viewer.src, alt: viewer.alt, caption: viewer.caption }]} onClose={() => setViewer(null)} />}
    </>
  )
}

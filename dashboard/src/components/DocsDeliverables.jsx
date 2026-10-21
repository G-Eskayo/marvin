import { useEffect, useState } from 'react'
import { formatDay, matchedBy } from '../lib/docs_view.js'
import { formatSize } from '../lib/file_kinds.js'

// Deliverables inside the Docs tab (#570, mock-ups docs/screenshots/ticket-403-f-*.png and h-2/h-3): the folder-card
// grid, a folder's item grid, the headers over a folder or file, and the #n ticket chip. Covers are 360 px thumbnails
// made once and cached on disk by the main process (outbox:thumb, behind the outbox guard); a small in-memory cache
// keeps a revisit instant.

const imageCache = new Map() // rel -> dataUrl | null, bounded
const IMAGE_CACHE_MAX = 200
export function useOutboxImage(rel) {
  const [url, setUrl] = useState(() => (rel ? imageCache.get(rel) ?? null : null))
  useEffect(() => {
    if (!rel) return setUrl(null)
    if (imageCache.has(rel)) return setUrl(imageCache.get(rel))
    let live = true
    window.api.outbox
      .thumb(rel)
      .then((t) => {
        const u = t?.ok ? t.dataUrl : null
        imageCache.set(rel, u)
        if (imageCache.size > IMAGE_CACHE_MAX) imageCache.delete(imageCache.keys().next().value)
        if (live) setUrl(u)
      })
      .catch(() => live && setUrl(null))
    return () => {
      live = false
    }
  }, [rel])
  return url
}

// The #n chip: the Markdown ticket-link classes; it opens the ticket on Activity.
export function TicketChip({ number, onOpen }) {
  if (!number) return null
  return (
    <span
      role="link"
      title={`Open ticket #${number}`}
      onClick={(e) => {
        e.stopPropagation()
        onOpen?.(number)
      }}
      className="ml-1 shrink-0 cursor-pointer rounded bg-blue-950 px-1 text-[10px] text-blue-300 hover:bg-blue-900"
    >
      #{number}
    </span>
  )
}

function Cover({ rel, kinds, tall = 'h-36' }) {
  const url = useOutboxImage(rel)
  return (
    <div className={`${tall} overflow-hidden bg-black`}>
      {url ? (
        <img src={url} alt="" className="h-full w-full object-cover object-top" />
      ) : (
        <div className="flex h-full items-center justify-center text-xs text-neutral-600">{(kinds || []).join(' · ') || 'File'}</div>
      )}
    </div>
  )
}

const card = 'overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900 text-left transition-colors hover:border-neutral-600'

// The project's folder-card grid (mock-up f-2): one card per deliverable, newest first.
export function DeliverablesGrid({ entries, onOpen, onTicket, title = true }) {
  if (!entries.length) return <p className="text-sm text-neutral-500">No deliverables matched to this project.</p>
  return (
    <div>
      {title && <p className="mb-3 text-xs text-neutral-500">Deliverables ({entries.length}) · newest first</p>}
      <div className="grid grid-cols-3 gap-3">
        {entries.map((e) => (
          <button key={e.path} onClick={() => onOpen(e)} className={card}>
            <Cover rel={e.covers?.[0]} kinds={e.kinds} />
            <div className="p-3">
              <p className="flex items-center text-sm font-medium text-white">
                <span className="truncate">{e.name}</span>
                <TicketChip number={e.ticket} onOpen={onTicket} />
              </p>
              <p className="mt-1 text-xs text-neutral-500">{[formatDay(e.date), e.isDir ? `${e.count} file${e.count === 1 ? '' : 's'}` : formatSize(e.size)].filter(Boolean).join(' · ')}</p>
              <p className="mt-1 truncate text-xs text-neutral-600" title={matchedBy(e)}>{matchedBy(e)}</p>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// The header over a selected deliverable folder or file (mock-ups h-2, f-1).
export function DeliverableHeader({ title, detail, onReveal }) {
  return (
    <div className="flex items-start gap-3 border-b border-neutral-900 px-6 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-white">{title}</p>
        <p className="mt-0.5 truncate text-[11px] text-neutral-500" title={detail}>{detail}</p>
      </div>
      <button onClick={onReveal} className="shrink-0 rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500">
        Reveal in Finder
      </button>
    </div>
  )
}

function ItemCard({ item, onOpen }) {
  const [info, setInfo] = useState(null)
  useEffect(() => {
    let live = true
    if (item.type === 'dir') window.api.outbox.summary(item.path).then((s) => live && setInfo(s)).catch(() => {})
    else if (item.kind === 'markdown' || item.kind === 'text') window.api.outbox.preview(item.path).then((p) => live && setInfo(p)).catch(() => {})
    return () => {
      live = false
    }
  }, [item.path])
  const cover = item.type === 'dir' ? info?.covers?.[0] : item.kind === 'image' ? item.path : null
  return (
    <button onClick={() => onOpen(item)} className={card}>
      {item.kind === 'markdown' && info?.title ? (
        <div className="h-40 overflow-hidden bg-black p-3">
          <p className="text-xs font-semibold text-white">{info.title}</p>
          <p className="mt-1 text-[11px] leading-snug text-neutral-400">{info.text}</p>
        </div>
      ) : (
        <Cover rel={cover} kinds={item.type === 'dir' ? info?.kinds : [item.label]} tall="h-40" />
      )}
      <div className="p-3">
        <p className="truncate text-sm font-medium text-white">{item.name}</p>
        <p className="mt-1 text-xs text-neutral-500">{item.type === 'dir' ? `Folder · ${info?.count ?? '…'} files` : item.label}</p>
      </div>
    </button>
  )
}

// A selected folder's contents as cards (mock-up h-2): images show a cover, markdown its first heading and opening
// text, subfolders their first image and file count.
export function FolderGrid({ listing, onOpen }) {
  if (!listing) return <p className="p-6 text-sm text-neutral-500">Loading…</p>
  return (
    <div className="p-6">
      <div className="grid grid-cols-4 gap-3">
        {listing.entries.map((item) => (
          <ItemCard key={item.path} item={item} onOpen={onOpen} />
        ))}
      </div>
      {listing.more > 0 && <p className="mt-3 text-xs text-neutral-500">{listing.more} more not shown</p>}
    </div>
  )
}

// Up to seven thumbnails for a deliverable search hit (mock-up f-4).
export function Thumbs({ rels }) {
  if (!rels?.length) return null
  return (
    <div className="mt-2 flex gap-2">
      {rels.slice(0, 7).map((r) => (
        <Thumb key={r} rel={r} />
      ))}
    </div>
  )
}
function Thumb({ rel }) {
  const url = useOutboxImage(rel)
  return <div className="h-20 w-12 overflow-hidden rounded bg-black">{url && <img src={url} alt="" className="h-full w-full object-cover object-top" />}</div>
}

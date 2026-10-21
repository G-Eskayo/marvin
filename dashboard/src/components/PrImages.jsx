import { useEffect, useState } from 'react'
import ImageViewer from './ImageViewer.jsx'

// The PR's images and recordings (mock-ups, screenshots, frame strips, GIFs, screen recordings) as a gallery at the top
// of the PR detail, with a full-size viewer. Owner, 2026-10-09: "when I click on the MR, if there are UI photos I want
// them rendered there", and he wants to SEE it working: GIFs animate (they're <img>) and recordings play inline.
// Bytes come from the main process (window.api.mr.image) so private repos load and the token stays out of the page.

// Images grouped under the PR's headings, keeping order; each item keeps its position in the flat list for the viewer.
export function groupImages(images) {
  const groups = []
  ;(images || []).forEach((img, index) => {
    const name = img.group || ''
    const last = groups[groups.length - 1]
    if (last && last.name === name) last.items.push({ ...img, index })
    else groups.push({ name, items: [{ ...img, index }] })
  })
  return groups
}

// Loads each image once, a few at a time, so a PR with many images doesn't flood GitHub.
export function useLoadedImages(images, loadImage, concurrency = 4) {
  const [state, setState] = useState({})
  const key = (images || []).map((i) => i.url).join('\n')
  useEffect(() => {
    let cancelled = false
    const kinds = Object.fromEntries((images || []).map((i) => [i.url, i.kind || null]))
    const queue = [...new Set((images || []).map((i) => i.url))]
    setState(Object.fromEntries(queue.map((url) => [url, { status: 'loading' }])))
    const worker = async () => {
      while (!cancelled && queue.length) {
        const url = queue.shift()
        let result
        try {
          result = await loadImage(url, kinds[url])
        } catch (error) {
          result = { ok: false, reason: String(error?.message || error) }
        }
        if (cancelled) return
        setState((s) => ({ ...s, [url]: result?.ok ? { status: 'ok', kind: result.kind === 'video' ? 'video' : 'image', src: result.src || result.dataUrl } : { status: 'error', reason: result?.reason || 'unknown error' } }))
      }
    }
    for (let i = 0; i < Math.min(concurrency, queue.length); i++) worker()
    return () => { cancelled = true }
  }, [key])
  return state
}

// A recording plays inline, muted and looping, so the motion shows without a click.
function Media({ s, alt, className }) {
  if (s.kind === 'video') {
    return <video src={s.src} aria-label={alt || 'Recording'} className={className} controls loop muted playsInline autoPlay />
  }
  return <img src={s.src} alt={alt} className={className} />
}

function Thumb({ img, loaded, onOpen }) {
  const s = loaded || { status: 'loading' }
  return (
    <figure className="flex flex-col gap-1">
      {s.status === 'ok' ? (
        s.kind === 'video' ? (
          <div className="relative overflow-hidden rounded-md border border-neutral-800 bg-neutral-950">
            <Media s={s} alt={img.alt} className="h-56 w-full object-contain" />
            <button onClick={onOpen} className="absolute right-2 top-2 rounded bg-black/70 px-2 py-1 text-xs text-neutral-200 hover:bg-black" title="Open full size">⤢ Full size</button>
          </div>
        ) : (
          <button onClick={onOpen} className="overflow-hidden rounded-md border border-neutral-800 bg-neutral-950 hover:border-neutral-500" title="Open full size">
            <Media s={s} alt={img.alt} className="h-56 w-full object-contain" />
          </button>
        )
      ) : s.status === 'error' ? (
        <div className="flex h-56 items-center justify-center rounded-md border border-red-900 bg-neutral-950 p-3 text-center text-xs text-red-400">
          couldn't load: {s.reason}
        </div>
      ) : (
        <div className="h-56 animate-pulse rounded-md bg-neutral-800" aria-label="Loading image" />
      )}
      {img.caption && <figcaption className="text-xs text-neutral-400">{img.kind === 'video' || s.kind === 'video' ? '▶ ' : ''}{img.caption}</figcaption>}
    </figure>
  )
}

// The full-size view is the shared ImageViewer (#402): ✕, Esc or a click outside closes it, and images zoom.
export function viewerItems(images, loaded) {
  return (images || []).map((img) => {
    const s = loaded[img.url] || { status: 'loading' }
    return { src: s.src, kind: s.kind, status: s.status, reason: s.reason, alt: img.alt, caption: img.caption, group: img.group }
  })
}

export default function PrImages({ images, loadImage = (url) => window.api.mr.image(url) }) {
  const loaded = useLoadedImages(images, loadImage)
  const [index, setIndex] = useState(null)
  if (!images || !images.length) return null
  return (
    <div className="flex flex-col gap-4">
      {groupImages(images).map((g, gi) => (
        <div key={`${gi}-${g.name}`}>
          {g.name && <h5 className="mb-2 text-sm font-medium text-neutral-200">{g.name}</h5>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {g.items.map((img) => (
              <Thumb key={img.url} img={img} loaded={loaded[img.url]} onOpen={() => setIndex(img.index)} />
            ))}
          </div>
        </div>
      ))}
      {index !== null && <ImageViewer items={viewerItems(images, loaded)} index={index} onIndex={setIndex} onClose={() => setIndex(null)} />}
    </div>
  )
}

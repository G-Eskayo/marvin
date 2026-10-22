// Deliverable text files already read, kept in the renderer (#570 speed budget: a markdown deliverable opens in under
// 50 ms). A cached open renders once, with no IPC round trip and no "Loading…" pass. Filled when a file is opened and,
// at idle, for the markdown/text files of a folder just expanded. Only text kinds under 200 KB; at most MAX entries
// (oldest dropped). Cleared whenever the outbox changes (the `outbox` trigger), so it can't show stale text.
const MAX = 40
const MAX_CHARS = 200 * 1024
const cache = new Map() // rel -> file
const TEXTISH = new Set(['markdown', 'text', 'json', 'table', 'code', 'notebook'])

export function getCachedFile(rel) {
  const f = cache.get(rel)
  if (!f) return null
  cache.delete(rel)
  cache.set(rel, f) // most recently used last
  return f
}

export function putCachedFile(rel, file) {
  if (!file || !TEXTISH.has(file.kind) || typeof file.content !== 'string' || file.content.length > MAX_CHARS) return
  cache.delete(rel)
  cache.set(rel, file)
  while (cache.size > MAX) cache.delete(cache.keys().next().value)
}

export function clearCachedFiles() {
  cache.clear()
}

export const cachedCount = () => cache.size

// At idle, read the text files of an expanded folder that are likely to be opened next (local reads, bounded).
export function prefetchTextFiles(entries, read, idle = globalThis.requestIdleCallback || ((fn) => fn())) {
  const wanted = (entries || []).filter((e) => e.type === 'file' && (e.kind === 'markdown' || e.kind === 'text') && !cache.has(e.path)).slice(0, 8)
  if (!wanted.length) return
  idle(() => {
    for (const e of wanted) read(e.path).then((f) => putCachedFile(e.path, f)).catch(() => {})
  })
}

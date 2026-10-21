// Saved state (marvin#236, #417): draw the last result instantly, then refresh behind it. Per-viewer convenience only:
// storage can be missing, full or throwing, and the page must work without it.
export function readSaved(storage, key) {
  try {
    const d = JSON.parse(storage?.getItem(key) ?? 'null')
    return d && typeof d.at === 'number' && 'value' in d ? d : null
  } catch {
    return null
  }
}

export function writeSaved(storage, key, value, now = Date.now()) {
  try {
    storage?.setItem(key, JSON.stringify({ at: now, value }))
  } catch {
    // quota or a private window: next launch just starts empty
  }
}

export function ageText(at, now = Date.now()) {
  const s = Math.max(0, (now - at) / 1000)
  if (s < 60) return 'updated just now'
  if (s < 3600) return `updated ${Math.floor(s / 60)} min ago`
  if (s < 86400) return `updated ${Math.floor(s / 3600)} h ago`
  const d = Math.floor(s / 86400)
  return `updated ${d} day${d === 1 ? '' : 's'} ago`
}

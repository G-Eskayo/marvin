// One back/forward history for the whole dashboard (#756), like a browser's: each entry is a screen, a tab plus what is
// open in it ({ tab: 'mr-review', item: 'pr:G-Eskayo/marvin#175' }; item null = the tab's list). Pure and immutable: a
// history value describes its own moment, so React state can hold it as is.
//
// Scroll position isn't kept here. Going back shows the same screen, and #755's scroll places (lib/scroll_places.js)
// key the position by the screen, so the list comes back where you left it without a second record of it.

export const MAX_ENTRIES = 100

const valid = (s) => !!s && typeof s.tab === 'string' && s.tab !== ''
const norm = (s) => ({ tab: s.tab, item: s.item ?? null })

export function sameScreen(a, b) {
  return !!a && !!b && a.tab === b.tab && (a.item ?? null) === (b.item ?? null)
}

export function startHistory(screen) {
  if (!valid(screen)) throw new Error('startHistory needs a screen with a tab')
  return { entries: [norm(screen)], index: 0 }
}

export function current(h) {
  return h.entries[h.index]
}

// Opening a screen: drops anything forward of here (as a browser does), and adds nothing if it's the screen already
// shown (a re-render, a refresh, a double click). Oldest entries go first past MAX_ENTRIES.
export function visit(h, screen) {
  if (!valid(screen) || sameScreen(current(h), screen)) return h
  const entries = [...h.entries.slice(0, h.index + 1), norm(screen)]
  const drop = Math.max(0, entries.length - MAX_ENTRIES)
  return { entries: entries.slice(drop), index: entries.length - 1 - drop }
}

// The nearest entry in `step` direction that still exists and isn't the screen already shown. available(screen) says
// whether an item can still be opened (a merged PR, a deleted doc can't); everything is available by default.
function step(h, dir, available) {
  const here = current(h)
  for (let i = h.index + dir; i >= 0 && i < h.entries.length; i += dir) {
    const s = h.entries[i]
    if (sameScreen(s, here) || !available(s)) continue
    return i
  }
  return -1
}

function move(h, dir, { available = () => true } = {}) {
  const i = step(h, dir, available)
  // Nothing to go to: the caller bounces; history is unchanged.
  if (i < 0) return { history: h, screen: null, edge: dir < 0 ? 'start' : 'end' }
  const history = { entries: h.entries, index: i }
  return { history, screen: current(history), edge: null }
}

export const back = (h, opts) => move(h, -1, opts)
export const forward = (h, opts) => move(h, 1, opts)
export const canGoBack = (h, { available = () => true } = {}) => step(h, -1, available) >= 0
export const canGoForward = (h, { available = () => true } = {}) => step(h, 1, available) >= 0

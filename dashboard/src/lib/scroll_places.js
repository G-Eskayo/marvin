// Where each screen was scrolled to (#755). One scroll box (the app's <main>, the Docs reading pane) shows many screens
// in turn: a list, then an item, then the list again. The browser keeps one scrollTop for the box, so a new screen
// inherited the last one's offset, clamped: an MR opened from far down the list opened at its own bottom. An area keys
// the position by what is on screen (the tab plus each view's part, e.g. "pr:G-Eskayo/marvin#175") and, when the key
// changes, puts the box where that screen was last left, or at the top for a screen never seen.
//
// The place is saved on every scroll event, not on the way out: by the time a switch is noticed the old content is
// already gone and the browser has clamped the offset. A restore the content can't reach yet (a list still loading)
// is retried as the content grows, until reached, until the user scrolls/clicks/types, or until RESTORE_WINDOW_MS.

export const RESTORE_WINDOW_MS = 3000
export const MAX_PLACES = 500

// The screen's key: the base (the tab) plus every view's part, in a fixed order so the same screen always has the
// same key. A view that shows nothing of its own (part null) adds nothing.
export function placeKey(base, segments) {
  const parts = [...segments].filter(([, v]) => v != null && v !== '').sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
  return [base ?? '', ...parts.map(([k, v]) => `${k}=${v}`)].join('|')
}

// store: Map shared by every area of the app, so a place outlives the component that drew it (a tab switch remounts).
// schedule: how a change is settled; a microtask by default, so several views changing in one render settle once,
// on the final screen, before the browser paints.
export function createScrollArea({ name, store, schedule = queueMicrotask, now = Date.now }) {
  let el = null
  let base = ''
  const segments = new Map()
  let current = null // the key the box is showing
  let pending = null // { target, until }: a restore the content couldn't reach yet
  let queued = false

  const id = (key) => `${name}|${key}`
  const save = (key, top) => {
    store.delete(id(key)) // re-insert so the Map's order is least-recently-saved first
    store.set(id(key), top)
    while (store.size > MAX_PLACES) store.delete(store.keys().next().value)
  }

  function settle() {
    queued = false
    if (!el) return
    const key = placeKey(base, segments)
    if (key === current) return
    current = key
    const target = store.get(id(key)) ?? 0
    el.scrollTop = target
    pending = el.scrollTop < target ? { target, until: now() + RESTORE_WINDOW_MS } : null
  }
  function changed() {
    if (queued) return
    queued = true
    schedule(settle)
  }

  return {
    attach(box) {
      el = box
      current = null
      pending = null
      changed()
    },
    detach() {
      el = null
      pending = null
    },
    setBase(key) {
      base = key
      changed()
    },
    setSegment(slot, value) {
      segments.set(slot, value)
      changed()
    },
    removeSegment(slot) {
      segments.delete(slot)
      changed()
    },
    onScroll() {
      // While a restore waits for content, the box's offset is a clamp, not the user's place.
      if (!el || pending || current === null) return
      save(current, el.scrollTop)
    },
    onContentResize() {
      if (!el || !pending) return
      if (now() > pending.until) { pending = null; return }
      el.scrollTop = pending.target
      if (el.scrollTop >= pending.target) pending = null
    },
    onUserInput() {
      pending = null
    },
    // A deliberate jump (a search hit, a heading link) wins over a restore still waiting for content.
    cancelRestore() {
      pending = null
    },
    saved() {
      return current === null ? undefined : store.get(id(current))
    }
  }
}

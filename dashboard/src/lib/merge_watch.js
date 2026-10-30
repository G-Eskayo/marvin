import { initialGate, onMergeEvent, gateEventOf, routeMerge, onListShown } from './merge_motion.js'

// The merge motion's ears (marvin#838): one subscription to the main process's merge pushes (mr:mergeEvent) for the
// window's lifetime, so a merge GitHub confirms while MR Review isn't on screen (another tab, inside an MR, the window
// hidden) is still counted and shown as a result when the list is back. The Open list attaches a listener while it
// is on screen; nothing is polled. Keys are PR urls, the key the merge ops use.
export function createMergeWatch() {
  let gate = initialGate()
  let route = { listVisible: false, pending: [] }
  let listener = null
  let subscribed = false
  const changed = new Set()

  const watch = {
    attach(api) {
      if (subscribed || !api?.mr?.onMergeEvent) return
      subscribed = true
      api.mr.onMergeEvent((url, op) => watch.event(url, op))
    },
    // One pushed op. Approve → waiting; GitHub confirms → play now (list on screen) or later; refused → the notice.
    event(url, op) {
      const type = gateEventOf(op)
      if (!type || typeof url !== 'string') return
      const r = onMergeEvent(gate, { type, key: url })
      gate = r.state
      if (r.refused && op.state === 'error') listener?.refused?.(url, op.reason || null)
      for (const key of r.play) {
        const x = routeMerge(route, key)
        route = x.state
        for (const k of x.play) listener?.play?.(k)
      }
      for (const f of changed) f()
    },
    isWaiting: (url) => gate.waiting.includes(url),
    isConfirmed: (url) => gate.done.includes(url),
    // The list is on screen. Returns what to do with what happened while it wasn't: { play, missed, note }.
    show(l, { focus = null } = {}) {
      listener = l
      const r = onListShown(route, { focus })
      route = r.state
      return r
    },
    hide() {
      route = { ...route, listVisible: false }
      listener = null
    },
    // Re-render on any change (the waiting border). Returns the unsubscribe.
    onChange(f) {
      changed.add(f)
      return () => changed.delete(f)
    }
  }
  return watch
}

export const mergeWatch = createMergeWatch()

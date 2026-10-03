import { watch as fsWatch } from 'fs'

// Event-driven refresh (CONTEXT.md "Triggers over polling"): trigger at the
// place state is stored, not at the places it's written. The hub turns file
// changes and external pings into debounced per-topic triggers; the
// reconciler is the coverage guard that notices when a slow poll found a
// change no trigger announced.
export function createTriggerHub({ debounceMs = 300, watch = fsWatch } = {}) {
  const listeners = new Set()
  const timers = new Map()
  const lastEmit = new Map()
  const watchers = []

  function emit(topic, source = 'unknown') {
    // Debounce per topic; the last source in a burst wins.
    clearTimeout(timers.get(topic))
    timers.set(
      topic,
      setTimeout(() => {
        timers.delete(topic)
        lastEmit.set(topic, Date.now())
        for (const cb of listeners) cb({ topic, source })
      }, debounceMs)
    )
  }

  function watchFiles(topic, targets) {
    for (const { dir, match } of targets) {
      try {
        watchers.push(watch(dir, (_event, name) => name && match(String(name)) && emit(topic, `file:${name}`)))
      } catch {
        // Directory doesn't exist yet or can't be watched: the backstop poll still covers it.
      }
    }
  }

  return {
    emit,
    watchFiles,
    onTrigger: (cb) => (listeners.add(cb), () => listeners.delete(cb)),
    lastEmitAt: (topic) => lastEmit.get(topic) ?? null,
    close: () => watchers.forEach((w) => w.close?.())
  }
}

// A poll that finds different data than last time, with no trigger fired in
// between, means some state changed without anyone announcing it: a gap.
export function createReconciler({ lastEmitAt, record, now = Date.now }) {
  const seen = new Map()
  return {
    observe(topic, key, digest, source) {
      const id = `${topic}|${key}`
      const prev = seen.get(id)
      const at = now()
      seen.set(id, { digest, at })
      if (!prev || source !== 'poll' || prev.digest === digest) return
      const fired = lastEmitAt(topic)
      if (fired !== null && fired > prev.at) return
      record({ topic, key, at: new Date(at).toISOString(), note: 'poll found a change no trigger announced' })
    }
  }
}

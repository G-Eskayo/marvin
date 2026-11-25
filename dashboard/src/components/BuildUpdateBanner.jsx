import { useEffect, useState } from 'react'
import { readSaved, writeSaved } from '../lib/saved_state.js'

// Guard access to window.api (doesn't exist in test environments)
const tryAccess = (fn) => {
  try {
    return fn()
  } catch {
    return undefined
  }
}

export default function BuildUpdateBanner() {
  const hasApi = typeof window !== 'undefined' && window.api?.build
  const [status, setStatus] = useState(null)
  const [demoHold, setDemoHold] = useState(false)
  const [showToast, setShowToast] = useState(false)

  useEffect(() => {
    if (!hasApi) return

    // Load initial status and demo-hold state.
    const load = async () => {
      try {
        const [s, dh] = await Promise.all([
          tryAccess(() => window.api.build?.status?.()) || Promise.resolve(null),
          tryAccess(() => window.api.build?.demoHold?.get?.()) || Promise.resolve(false)
        ])
        setStatus(s)
        setDemoHold(dh)
        if (s?.shouldShowOnceToast) {
          setShowToast(true)
        }
      } catch (err) {
        console.error('Failed to load build status:', err)
      }
    }
    load()

    // Listen for build ready events via the trigger hub.
    const offTrigger = tryAccess(() => window.api.triggers?.on?.((t) => {
      if (t.topic === 'build') {
        setStatus(prev => ({
          ...prev,
          shouldNotify: true,
          shouldShowOnceToast: true
        }))
        setShowToast(true)
        // Re-fetch the current status to get the latest ready details.
        window.api.build?.status?.().then(s => {
          if (s) setStatus(s)
        }).catch(() => {})
      }
    })) || (() => {})

    return () => offTrigger()
  }, [hasApi])

  const handleRestart = () => {
    window.api.build?.restartNow?.()
  }

  const handleLater = () => {
    setShowToast(false)
    if (status?.ready?.sha) {
      // Record that the user chose 'Later' for this SHA so we can auto-restart on next focus.
      writeSaved(typeof sessionStorage !== 'undefined' ? sessionStorage : null, `build-action-${status.ready.sha}`, 'later')
    }
  }

  const handleDemoHoldToggle = async () => {
    if (!hasApi) return
    const newState = !demoHold
    setDemoHold(newState)  // Optimistic update
    try {
      await window.api.build?.demoHold?.set?.(newState)
    } catch (err) {
      // Revert on failure (e.g., permission denied)
      setDemoHold(!newState)
      console.error('Failed to toggle demo hold:', err)
    }
  }

  const shouldShow = status?.shouldNotify && status?.ready?.sha

  return (
    <>
      {showToast && shouldShow && (
        <div className="fixed bottom-4 right-4 z-50 rounded-lg bg-blue-600 text-white p-4 shadow-lg max-w-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="font-semibold">Update ready</h3>
              <p className="text-sm text-blue-100 mt-1">A new version of MARVIN is installed and ready.</p>
            </div>
            <button
              onClick={() => setShowToast(false)}
              className="text-blue-100 hover:text-white shrink-0"
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <div className="flex gap-2 mt-3">
            <button
              onClick={handleRestart}
              className="px-3 py-1 rounded bg-blue-700 hover:bg-blue-800 text-sm font-medium"
            >
              Restart now
            </button>
            <button
              onClick={handleLater}
              className="px-3 py-1 rounded bg-blue-500 hover:bg-blue-600 text-sm font-medium"
            >
              Later
            </button>
          </div>
        </div>
      )}

      {shouldShow && !showToast && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 px-4 py-2 flex items-center justify-between gap-2 text-sm">
          <span className="text-blue-900 dark:text-blue-100">
            Update ready · Restart to apply
          </span>
          <button
            onClick={handleRestart}
            className="px-2 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium"
          >
            Restart
          </button>
        </div>
      )}

      <div className="border-b border-neutral-800 px-6 py-2 flex items-center justify-between bg-neutral-900/50">
        <label className="flex items-center gap-2 text-sm text-neutral-400 hover:text-neutral-200 cursor-pointer">
          <input
            type="checkbox"
            checked={demoHold}
            onChange={handleDemoHoldToggle}
            className="rounded"
          />
          Demo hold (skip rebuilds)
        </label>
      </div>
    </>
  )
}

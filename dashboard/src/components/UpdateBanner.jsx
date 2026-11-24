import { useEffect, useState } from 'react'

function DemoHoldSwitch({ enabled, onChange }) {
  return (
    <label className="flex items-start gap-2 rounded-md border border-neutral-800 bg-neutral-900/40 p-3 text-sm text-neutral-200">
      <input
        type="checkbox"
        checked={enabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1"
      />
      <span>
        Demo/screenshot mode (pause updates)
        <span className="block text-xs text-neutral-500">
          While on, the dashboard will not apply staged updates. Use this when you're taking screenshots or recording.
        </span>
      </span>
    </label>
  )
}

export default function UpdateBanner() {
  const [demoHold, setDemoHold] = useState(false)
  const [updateReady, setUpdateReady] = useState(null)
  const [lastSha, setLastSha] = useState(null)
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    const checkDemoHold = async () => {
      const enabled = await window.api.app.getDemoHold()
      setDemoHold(enabled)
    }
    const checkLastUpdate = async () => {
      const result = await window.api.app.lastUpdate()
      setLastSha(result?.sha || null)
    }
    checkDemoHold()
    checkLastUpdate()

    // Listen for update ready notifications
    const unsubscribe = window.api.app.onUpdateReady(({ sha }) => {
      setUpdateReady({ sha })
    })
    return unsubscribe
  }, [])

  const handleDemoHoldChange = async (enabled) => {
    setDemoHold(enabled)
    await window.api.app.setDemoHold(enabled)
  }

  const handleRestartNow = async () => {
    setRestarting(true)
    try {
      await window.api.app.restartForUpdate()
    } catch (err) {
      console.error('[UpdateBanner] restart failed:', err)
      setRestarting(false)
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
      <div>
        <h3 className="text-sm font-semibold text-neutral-100">Demo & Updates</h3>
      </div>

      <DemoHoldSwitch enabled={demoHold} onChange={handleDemoHoldChange} />

      {updateReady && (
        <div className="rounded-md border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-200">
          <div className="mb-2 flex items-center justify-between">
            <span>
              Update ready to {updateReady.sha}
              <span className="ml-2 inline text-xs text-amber-500">staged and waiting for idle</span>
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleRestartNow}
              disabled={restarting}
              className="rounded px-3 py-1 text-xs font-medium bg-amber-700 hover:bg-amber-600 disabled:bg-neutral-700 disabled:text-neutral-500"
            >
              {restarting ? 'Restarting...' : 'Restart now'}
            </button>
            <span className="text-xs text-amber-500">or use the app normally (will restart when idle)</span>
          </div>
        </div>
      )}

      {lastSha && !updateReady && (
        <p className="text-xs text-neutral-400">
          Last update: {lastSha}
        </p>
      )}
    </div>
  )
}

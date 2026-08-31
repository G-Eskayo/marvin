import { useEffect, useState } from 'react'
import MetricsScorecard from '@components/MetricsScorecard.jsx'
import MrReview from '@components/MrReview.jsx'
import DispatchStatusBadge from '@components/DispatchStatusBadge.jsx'

const TABS = [
  { id: 'metrics', label: 'Metrics' },
  { id: 'mr-review', label: 'MR Review' }
]

const DOT_COLOR = {
  red: 'bg-red-500',
  blue: 'bg-blue-500',
  green: 'bg-emerald-500'
}

const STATUS_LABEL = {
  red: 'New PR(s) awaiting your first look',
  blue: 'Open PR(s), already seen, still awaiting approval',
  green: 'Nothing awaiting review'
}

// Refreshed on window.api.mr.onRefresh -- pushed the moment mr_raiser.py
// raises a PR (see webhook-server/refresh_relay.js + electron/main/
// refresh_server.js) -- so this is a safety net for whatever that push
// misses (Electron wasn't running yet when the ping arrived, the ping
// came from the other machine, etc.), not the primary update path.
const FALLBACK_POLL_MS = 120000

export default function App() {
  const [activeTab, setActiveTab] = useState('metrics')
  const [reviewStatus, setReviewStatus] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function refresh() {
      try {
        const result = await window.api.mr.reviewStatus()
        if (!cancelled) setReviewStatus(result)
      } catch {
        // Status dot is a nice-to-have -- a failed fetch just leaves the
        // last known state rather than surfacing an error anywhere.
      }
    }
    refresh()
    const interval = setInterval(refresh, FALLBACK_POLL_MS)
    const unsubscribe = window.api.mr.onRefresh(refresh)
    return () => {
      cancelled = true
      clearInterval(interval)
      unsubscribe()
    }
  }, [])

  useEffect(() => {
    if (activeTab !== 'mr-review') return
    window.api.mr
      .reviewStatus()
      .then(setReviewStatus)
      .catch(() => {})
  }, [activeTab])

  return (
    <div className="flex h-screen flex-col">
      <header className="flex shrink-0 items-center gap-1 border-b border-neutral-800 px-6 pb-3 pt-12">
        <h1 className="mr-6 text-sm font-semibold tracking-wide text-neutral-400">MARVIN METRICS</h1>
        <nav className="flex gap-1">
          {TABS.map((tab) => {
            const dot = tab.id === 'mr-review' ? reviewStatus?.status : null
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                title={dot ? STATUS_LABEL[dot] : undefined}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                  activeTab === tab.id
                    ? 'bg-neutral-800 text-white'
                    : 'text-neutral-400 hover:text-neutral-200'
                }`}
              >
                {dot && <span className={`h-2 w-2 shrink-0 rounded-full ${DOT_COLOR[dot]}`} />}
                {tab.label}
              </button>
            )
          })}
        </nav>
        <div className="ml-auto">
          <DispatchStatusBadge />
        </div>
      </header>
      <main className="flex-1 overflow-auto">
        {activeTab === 'metrics' ? <MetricsScorecard /> : <MrReview />}
      </main>
    </div>
  )
}

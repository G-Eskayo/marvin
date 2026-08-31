import { useEffect, useState } from 'react'
import MetricsScorecard from '@components/MetricsScorecard.jsx'
import MrReview from '@components/MrReview.jsx'

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

// Polled independently of which tab is active so the dot is accurate even
// if you never open MR Review -- that's the whole point of a glanceable
// status indicator. Also re-fetched immediately on switching into the tab,
// since MrReview marks its list seen right after loading and the poll
// interval alone would leave a stale red dot showing for up to REFRESH_MS.
const REFRESH_MS = 15000

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
    const interval = setInterval(refresh, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
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
                className={`relative rounded-md px-3 py-1.5 text-sm transition-colors ${
                  activeTab === tab.id
                    ? 'bg-neutral-800 text-white'
                    : 'text-neutral-400 hover:text-neutral-200'
                }`}
              >
                {tab.label}
                {dot && (
                  <span
                    className={`absolute right-1 top-1 h-1.5 w-1.5 rounded-full ${DOT_COLOR[dot]}`}
                  />
                )}
              </button>
            )
          })}
        </nav>
      </header>
      <main className="flex-1 overflow-auto">
        {activeTab === 'metrics' ? <MetricsScorecard /> : <MrReview />}
      </main>
    </div>
  )
}

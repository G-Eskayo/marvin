import { useEffect, useState } from 'react'
import MetricsPage from '@components/MetricsPage.jsx'
import MrReview from '@components/MrReview.jsx'
import HealthDashboard from '@components/HealthDashboard.jsx'
import DocsExplorer from '@components/DocsExplorer.jsx'
import ActivityBoard from '@components/ActivityBoard.jsx'
import PortfolioHub from '@components/PortfolioHub.jsx'
import SuggestionsPage from '@components/SuggestionsPage.jsx'
import DispatchStatusBadge from '@components/DispatchStatusBadge.jsx'
import MarvinButton from '@components/MarvinButton.jsx'
import ActivityHover from '@components/ActivityHover.jsx'

const TABS = [
  { id: 'metrics', label: 'Metrics' },
  { id: 'mr-review', label: 'MR Review' },
  { id: 'health', label: 'Health' },
  { id: 'docs', label: 'Docs' },
  { id: 'activity', label: 'Activity' },
  { id: 'suggestions', label: 'Suggestions' },
  { id: 'portfolio', label: 'Portfolio' }
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

const HEALTH_DOT_COLOR = {
  red: 'bg-red-500',
  yellow: 'bg-amber-500',
  green: 'bg-emerald-500'
}

export default function App() {
  const [activeTab, setActiveTab] = useState('metrics')
  // Cross-tab links by project: { tab, ...target, at } -- the target tab reads what it needs
  // (prKey for MR Review, projectId for Docs, repo for Activity) and acts once per `at`.
  const [nav, setNav] = useState(null)
  const navigate = (tab, target = {}) => {
    setNav({ ...target, tab, at: Date.now() })
    setActiveTab(tab)
  }
  const [reviewStatus, setReviewStatus] = useState(null)
  const [healthOverall, setHealthOverall] = useState(null)

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

  useEffect(() => {
    let cancelled = false
    function refreshHealthDot() {
      window.api.health
        .status()
        .then((result) => {
          if (!cancelled) setHealthOverall(result.overall)
        })
        .catch(() => {})
    }
    refreshHealthDot()
    const interval = setInterval(refreshHealthDot, 60_000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <div className="flex h-screen flex-col">
      <header className="titlebar flex shrink-0 items-center gap-1 border-b border-neutral-800 px-6 pb-3 pt-12">
        <h1 className="mr-6 text-sm font-semibold tracking-wide text-neutral-400">MARVIN METRICS</h1>
        <nav className="flex gap-1">
          {TABS.map((tab) => {
            const dot = tab.id === 'mr-review' ? reviewStatus?.status : tab.id === 'health' ? healthOverall : null
            const dotColorMap = tab.id === 'health' ? HEALTH_DOT_COLOR : DOT_COLOR
            const title = tab.id === 'mr-review' ? STATUS_LABEL[dot] : tab.id === 'health' && dot ? `Overall: ${dot}` : undefined
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                title={title}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                  activeTab === tab.id
                    ? 'bg-neutral-800 text-white'
                    : 'text-neutral-400 hover:text-neutral-200'
                }`}
              >
                {dot && <span className={`h-2 w-2 shrink-0 rounded-full ${dotColorMap[dot]}`} />}
                {tab.label}
              </button>
            )
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <MarvinButton />
          <ActivityHover>
            <DispatchStatusBadge onClick={() => navigate('health', { view: 'agents' })} />
          </ActivityHover>
        </div>
      </header>
      <main className="flex-1 overflow-auto">
        {activeTab === 'metrics' ? (
          <MetricsPage />
        ) : activeTab === 'mr-review' ? (
          <MrReview nav={nav} onOpenDocs={(projectId, path) => navigate('docs', { projectId, path })} onOpenBoard={(repo) => navigate('activity', { repo })} onOpenTicket={(repo, number) => navigate('activity', { repo, ticketNumber: number })} />
        ) : activeTab === 'health' ? (
          <HealthDashboard nav={nav} />
        ) : activeTab === 'docs' ? (
          <DocsExplorer nav={nav} onOpenBoard={(repo) => navigate('activity', { repo })} onOpenTicket={(repo, number) => navigate('activity', { repo, ticketNumber: number })} onOpenPr={(repo, number) => navigate('mr-review', { prKey: `${repo}#${number}` })} />
        ) : activeTab === 'suggestions' ? (
          <SuggestionsPage />
        ) : activeTab === 'portfolio' ? (
          <PortfolioHub />
        ) : (
          <ActivityBoard nav={nav} onOpenMr={(prKey) => navigate('mr-review', { prKey })} onOpenDocs={(projectId, path) => navigate('docs', { projectId, path })} onOpenTicket={(repo, number) => navigate('activity', { repo, ticketNumber: number })} onOpenProject={(repo) => navigate('activity', { repo })} />
        )}
      </main>
    </div>
  )
}
